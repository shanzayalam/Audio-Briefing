"""
Script Writer Module

Generates news scripts using GPT-4o-mini with adaptive detail levels.
"""

from typing import List, Dict, Any
from dataclasses import dataclass
from research_analyst import ArticleAnalysis
from openai import OpenAI
import os
from dotenv import load_dotenv
from prompt_loader import prompt_loader
from opik_config import track, instrument_openai_client
# Initialize OpenAI
openai_client = instrument_openai_client(OpenAI())


@dataclass
class NewsScript:
    """Complete news script ready for delivery"""
    full_script: str
    segments: List[Dict[str, Any]]  # Individual article segments
    total_word_count: int
    estimated_duration: int  # seconds
    intro: str
    outro: str
    metadata: Dict[str, Any]


class ScriptWriter:
    """
    Script Writer - Second role in the newsroom pipeline
    Converts analyzed articles into a cohesive news script
    """
    
    def __init__(self, use_ai: bool = True, news_style: str = "professional", language: str = "english"):
        """
        Initialize the script writer
        
        Args:
            use_ai: Whether to use AI (GPT) for script writing
            news_style: Style of delivery (professional, conversational, formal)
            language: Language for script generation ('english', 'arabic', etc.)
        """
        self.use_ai = use_ai
        self.news_style = news_style
        self.language = language
        
        # Style templates
        self.style_prompts = {
            "professional": "Write like a BBC or NPR news anchor - authoritative yet accessible",
            "conversational": "Write like a podcast host - friendly and engaging but informative",
            "formal": "Write like a traditional evening news anchor - serious and dignified"
        }
    

    def write_script(
        self, 
        analyzed_articles: List[ArticleAnalysis],
        briefing_title: str = "Daily News Briefing",
        words_per_minute: int = 150
    ) -> NewsScript:
        """
        Write complete news script from analyzed articles
        
        Args:
            analyzed_articles: Articles from research analyst
            briefing_title: Title of the briefing
            words_per_minute: Speaking rate
            
        Returns:
            Complete NewsScript object
            
        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If script generation fails
        """
        
        # Validate inputs
        if not analyzed_articles or len(analyzed_articles) == 0:
            raise ValueError("No articles provided for script writing")
        
        if not briefing_title or not briefing_title.strip():
            briefing_title = "Daily News Briefing"
        
        if words_per_minute <= 0:
            raise ValueError(f"Invalid words per minute: {words_per_minute}. Must be positive.")
        
        try:
            # Write intro
            intro = self._write_intro(briefing_title, len(analyzed_articles))
            
            if not intro or not intro.strip():
                raise ValueError("Failed to generate introduction")
        except Exception as e:
            raise RuntimeError(f"Failed to write introduction: {e}") from e
        
        # Write individual segments
        segments = []
        failed_segments = []
        
        for article in analyzed_articles:
            try:
                segment = self._write_article_segment(article)
                
                if segment and segment.get('script'):
                    segments.append(segment)
                else:
                    failed_segments.append(article.article_id)
                    print(f"Warning: Failed to generate segment for article {article.article_id}")
                    
            except Exception as e:
                failed_segments.append(article.article_id)
                print(f"Warning: Error writing segment for article {article.article_id}: {e}")
                continue
        
        # Check if we have enough segments
        if not segments:
            raise RuntimeError(f"Failed to generate any article segments from {len(analyzed_articles)} articles")
        
        if failed_segments:
            print(f"Warning: {len(failed_segments)} segment(s) failed: {failed_segments}")
        
        try:
            # Write outro
            outro = self._write_outro()
            
            if not outro or not outro.strip():
                # Use default outro if generation fails
                outro = "That concludes today's briefing. Stay informed, stay ahead."
        except Exception as e:
            print(f"Warning: Failed to write outro: {e}. Using default.")
            outro = "That concludes today's briefing. Stay informed, stay ahead."
        
        try:
            # Combine all segments with transitions
            full_script = self._assemble_script(intro, segments, outro)
            
            if not full_script or not full_script.strip():
                raise ValueError("Assembled script is empty")
        except Exception as e:
            raise RuntimeError(f"Failed to assemble script: {e}") from e
        
        # Calculate metrics
        try:
            total_words = len(full_script.split())
            
            if total_words == 0:
                raise ValueError("Script has zero words")
            
            estimated_duration = int((total_words / words_per_minute) * 60)
        except Exception as e:
            raise RuntimeError(f"Failed to calculate script metrics: {e}") from e
        
        return NewsScript(
            full_script=full_script,
            segments=segments,
            total_word_count=total_words,
            estimated_duration=estimated_duration,
            intro=intro,
            outro=outro,
            metadata={
                "article_count": len(analyzed_articles),
                "successful_segments": len(segments),
                "failed_segments": len(failed_segments),
                "categories": list(set(a.category for a in analyzed_articles)),
                "total_time_allocated": sum(a.time_allocation for a in analyzed_articles)
            }
        )
    
    @track(name="script_write_intro")
    def _write_intro(self, briefing_title: str, article_count: int) -> str:
        """Write opening segment"""
        
        if self.use_ai:
            prompt = prompt_loader.get_user_prompt(
                "script_writer_intro",
                style=self.style_prompts[self.news_style],
                briefing_title=briefing_title,
                article_count=article_count
            )

            try:
                system_prompt = prompt_loader.get_system_prompt("script_writer_intro")
                
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=100
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"AI intro generation failed: {e}")
                return self._default_intro(briefing_title, article_count)
        else:
            return self._default_intro(briefing_title, article_count)
    
    def _default_intro(self, briefing_title: str, article_count: int) -> str:
        """Default template intro"""
        from datetime import datetime
        time_greeting = "morning" if datetime.now().hour < 12 else "afternoon" if datetime.now().hour < 18 else "evening"
        return f"Good {time_greeting}, and welcome to {briefing_title}. I'm bringing you {article_count} essential stories shaping today's headlines. Let's dive in."
    
    def _write_article_segment(self, article: ArticleAnalysis) -> Dict[str, Any]:
        """Write script for a single article"""
        
        if self.use_ai:
            return self._ai_write_segment(article)
        else:
            return self._template_write_segment(article)
    

    @track(name="script_ai_write_segment")
    def _ai_write_segment(self, article: ArticleAnalysis) -> Dict[str, Any]:
        """Use AI to write article segment"""
        
        # Validate article has required fields
        if not article or not article.title:
            print(f"Warning: Invalid article object, using template fallback")
            return self._template_write_segment(article)
        
        # Audio formatting rules
        formatting_rules = "\n\n**Audio Formatting (CRITICAL):**\n" \
                           "   * **No Abbreviations:** Expand all abbreviations (e.g., write 'United States' instead of 'US', 'percent' instead of '%', 'kilometers' instead of 'km').\n" \
                           "   * **Numbers:** Write out important numbers if needed for clarity (e.g. 'million').\n" \
                           "   * **Currencies:** Always write currencies as '[Amount] [Currency Name]' (e.g., write '15 Dirhams' instead of 'Dh 15', '20 Dollars' instead of '$20', '100 Rupees' instead of '₹100')."

        # Adjust prompt based on urgency/time allocation
        if article.urgency == "high":
            instruction = f"Write a detailed news segment of approximately {article.word_count_target} words. Include context and key details.{formatting_rules}"
        elif article.urgency == "normal":
            instruction = f"Write a concise news segment of approximately {article.word_count_target} words. Focus on the main points.{formatting_rules}"
        else:
            instruction = f"Write a brief news segment of approximately {article.word_count_target} words. Cover only the essential information.{formatting_rules}"
        
        key_points_text = chr(10).join(f"- {point}" for point in article.key_points)
        
        prompt = prompt_loader.get_user_prompt(
            "script_writer_article",
            style=self.style_prompts[self.news_style],
            instruction=instruction,
            title=article.title,
            source=article.source,
            category=article.category,
            key_points=key_points_text,
            content=f"{article.content[:500]}...",
            word_count_target=article.word_count_target
        )
        
        try:
            system_prompt = prompt_loader.get_system_prompt("script_writer_article")
            
            # Append critical formatting rules to system prompt for stricter enforcement
            system_prompt += (
                "\n\nCRITICAL OUTPUT RULES:\n"
                "1. NO ABBREVIATIONS: Expand 'US' to 'United States', 'km' to 'kilometers', etc.\n"
                "2. CURRENCIES: write as '[Number] [Currency Name]'.\n"
                "   - 'Dh547 billion' -> '547 billion Dirhams'\n"
                "   - 'QAR 314,535,182' -> '314 million Qatari Riyals' (approximate large numbers)\n"
                "   - '$15' -> '15 Dollars'\n"
                "3. NUMBERS: Write '547 billion' instead of '547000000000'.\n"
                "4. SPEAKABLE TEXT: The output must be ready to read aloud immediately."
            )
            
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=article.word_count_target * 2,
                timeout=30.0  # 30 second timeout
            )
            
            if not response or not response.choices:
                raise ValueError("Empty response from OpenAI API")
            
            script_text = response.choices[0].message.content
            
            if not script_text or not script_text.strip():
                raise ValueError("Empty script text in OpenAI response")
            
            script_text = script_text.strip()
            
            return {
                "article_id": article.article_id,
                "title": article.title,
                "category": article.category,
                "script": script_text,
                "word_count": len(script_text.split()),
                "target_word_count": article.word_count_target,
                "urgency": article.urgency
            }
            
        except Exception as e:
            # Catch all OpenAI exceptions and use fallback
            error_msg = str(e)
            if "APIError" in error_msg or "RateLimitError" in error_msg or "APITimeoutError" in error_msg:
                print(f"OpenAI API error for {article.article_id}: {e}. Using template fallback.")
            else:
                print(f"Error writing segment for {article.article_id}: {e}. Using template fallback.")
            return self._template_write_segment(article)
        except ValueError as e:
            print(f"Validation error for {article.article_id}: {e}. Using template fallback.")
            return self._template_write_segment(article)
        except Exception as e:
            print(f"Unexpected error writing segment for {article.article_id}: {e}. Using template fallback.")
            return self._template_write_segment(article)
    
    def _template_write_segment(self, article: ArticleAnalysis) -> Dict[str, Any]:
        """Template-based segment writing"""
        
        # Varied opening phrases
        openings = [
            "{title}... {point}",
            "Breaking in {category}: {point}",
            "{point}",
            "From {source}, {point}",
            "In a major development, {point}"
        ]
        
        # Simple template approach
        if article.key_points:
            main_point = article.key_points[0]
        else:
            # Extract first sentence from content
            sentences = article.content.split('.')
            main_point = sentences[0] if sentences else article.title
        
        # Select opening based on urgency
        if article.urgency == "high":
            import random
            template = random.choice(openings[:3])  # More direct openings
            script = template.format(
                title=article.title,
                category=article.category,
                point=main_point,
                source=article.source
            )
            if len(article.key_points) > 1:
                script += f" ... {article.key_points[1]}"
        else:
            script = f"{main_point}."
        
        return {
            "article_id": article.article_id,
            "title": article.title,
            "category": article.category,
            "script": script,
            "word_count": len(script.split()),
            "target_word_count": article.word_count_target,
            "urgency": article.urgency
        }
    

    def _write_outro(self) -> str:
        """Write closing segment"""
        
        if self.use_ai:
            prompt = prompt_loader.get_user_prompt("script_writer_outro")

            try:
                system_prompt = prompt_loader.get_system_prompt("script_writer_outro")
                
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=100
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"AI outro generation failed: {e}")
                return self._default_outro()
        else:
            return self._default_outro()
    
    def _default_outro(self) -> str:
        """Default template outro"""
        from datetime import datetime
        return f"That's your briefing for {datetime.now().strftime('%B %d')}. Stay informed, stay ahead. I'm your briefing assistant, and we'll talk soon."
    
    def _assemble_script(
        self, 
        intro: str, 
        segments: List[Dict[str, Any]], 
        outro: str
    ) -> str:
        """Assemble complete script with transitions"""
        
        script_parts = [intro]
        
        # Group segments by category for better flow
        categorized = {}
        for segment in segments:
            category = segment['category']
            if category not in categorized:
                categorized[category] = []
            categorized[category].append(segment)
        
        # Add segments with transitions
        previous_category = None
        for segment in segments:
            current_category = segment['category']
            
            # Add transition if category changes (for high/medium priority items)
            if (previous_category and 
                current_category != previous_category and 
                segment['urgency'] in ['high', 'normal']):
                transition = self._create_transition(previous_category, current_category)
                if transition:
                    script_parts.append(transition)
            
            script_parts.append(segment['script'])
            previous_category = current_category
        
        script_parts.append(outro)
        
        # Join with appropriate spacing
        return "\n\n".join(script_parts)
    
    def _create_transition(self, from_category: str, to_category: str) -> str:
        """Create smooth transition between categories"""
        
        # Smart transitions based on category combinations
        transition_map = {
            ("politics", "economy"): "Shifting to economic developments,",
            ("economy", "technology"): "In the technology sector,",
            ("technology", "health"): "Turning to health and medicine,",
            ("economy", "lifestyle"): "On a different note,",
            ("breaking", "politics"): "In political news,",
            ("politics", "breaking"): "Breaking now,",
        }
        
        # Try to find specific transition
        key = (from_category, to_category)
        if key in transition_map:
            return transition_map[key]
        
        # Generic transitions
        generic = [
            "Meanwhile,",
            "In other developments,",
            f"Moving to {to_category},"
        ]
        
        # Return based on categories
        import random
        return random.choice(generic) if from_category != to_category else ""
    
    def export_script(self, script: NewsScript, filepath: str) -> None:
        """Export script to text file"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"NEWS BRIEFING SCRIPT\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(f"Total Word Count: {script.total_word_count}\n")
            f.write(f"Estimated Duration: {script.estimated_duration} seconds\n")
            f.write(f"Number of Stories: {script.metadata['article_count']}\n\n")
            f.write(f"{'=' * 60}\n\n")
            f.write(script.full_script)
            f.write(f"\n\n{'=' * 60}\n")
            f.write(f"END OF SCRIPT\n")

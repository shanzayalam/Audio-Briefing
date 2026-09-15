"""
Research Analyst Module

"""

from typing import List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import re
from collections import Counter
from openai import OpenAI
import os
from dotenv import load_dotenv
from prompt_loader import prompt_loader
from opik_config import track, instrument_openai_client
# Initialize OpenAI
openai_client = instrument_openai_client(OpenAI())


@dataclass
class ArticleAnalysis:
    """Analyzed article with metadata and priority"""
    article_id: str
    title: str
    content: str
    source: str
    published_date: str
    
    # Analysis results
    importance_score: float  # 0-10 scale
    category: str
    key_points: List[str]
    entities: List[str]
    sentiment: str  # positive, negative, neutral
    time_allocation: int  # seconds allocated
    word_count_target: int  # target words for this article
    
    # Metadata
    original_word_count: int = 0
    urgency: str = "normal"  # breaking, high, normal, low


class ResearchAnalyst:
    """
    Research Analyst - First role in the pipeline
    Analyzes articles and determines their importance and allocation
    Domain-agnostic: works with any content type (news, real estate, finance, etc.)
    """
    
    def __init__(self, use_ai: bool = True, domain: str = "general"):
        """
        Initialize the research analyst
        
        Args:
            use_ai: Whether to use AI (GPT) for analysis or rule-based approach
            domain: Content domain (general, real_estate, finance, technology, health, etc.)
        """
        self.use_ai = use_ai
        self.domain = domain
        
        # Default category weights - can be customized per domain
        self.category_weights = self._get_domain_weights()
    
    def _get_domain_weights(self) -> Dict[str, int]:
        """Get category weights based on domain"""
        
        # Default general/news weights
        general_weights = {
            "breaking": 10,
            "urgent": 9,
            "high_priority": 8,
            "medium_priority": 6,
            "low_priority": 4,
            "other": 5
        }
        
        # Real estate specific weights
        real_estate_weights = {
            "market_trends": 9,
            "development": 8,
            "commercial": 8,
            "financing": 7,
            "investment": 7,
            "regulatory": 7,
            "technology": 6,
            "sustainability": 6,
            "affordable_housing": 7,
            "hospitality": 6,
            "retail": 6,
            "industrial": 7,
            "other": 5
        }
        
        # Finance/investment weights
        finance_weights = {
            "breaking": 10,
            "markets": 9,
            "policy": 8,
            "earnings": 8,
            "analysis": 7,
            "crypto": 6,
            "commodities": 6,
            "forex": 6,
            "other": 5
        }
        
        # Technology weights
        tech_weights = {
            "breaking": 10,
            "ai": 9,
            "cybersecurity": 8,
            "startups": 7,
            "products": 7,
            "research": 7,
            "policy": 6,
            "other": 5
        }
        
        domain_weights = {
            "general": general_weights,
            "news": general_weights,
            "real_estate": real_estate_weights,
            "finance": finance_weights,
            "technology": tech_weights,
        }
        
        return domain_weights.get(self.domain, general_weights)
    
    def analyze_articles(
        self, 
        articles: List[Dict[str, Any]], 
        target_duration: int = 300,
        words_per_minute: int = 150
    ) -> List[ArticleAnalysis]:
        """
        Analyze all articles and assign priorities
        
        Args:
            articles: List of article dictionaries
            target_duration: Target duration in seconds (default 5 minutes)
            words_per_minute: Speaking rate
            
        Returns:
            List of analyzed articles with priorities
            
        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If analysis fails completely
        """
        # Validate inputs
        if not articles or len(articles) == 0:
            raise ValueError("No articles provided for analysis")
        
        if target_duration <= 0:
            raise ValueError(f"Invalid target duration: {target_duration}. Must be positive.")
        
        if words_per_minute <= 0:
            raise ValueError(f"Invalid words per minute: {words_per_minute}. Must be positive.")
        
        analyzed_articles = []
        failed_articles = []
        
        # Step 1: Initial analysis and scoring
        for idx, article in enumerate(articles):
            try:
                # Validate article structure
                if not isinstance(article, dict):
                    raise TypeError(f"Article {idx} is not a dictionary")
                
                analysis = self._analyze_single_article(article, idx)
                
                if analysis:
                    analyzed_articles.append(analysis)
                else:
                    failed_articles.append(idx)
                    
            except Exception as e:
                print(f"Warning: Failed to analyze article {idx}: {e}")
                failed_articles.append(idx)
                continue
        
        # Check if we have any successful analyses
        if not analyzed_articles:
            raise RuntimeError(f"Failed to analyze all {len(articles)} articles")
        
        if failed_articles:
            print(f"Warning: {len(failed_articles)} article(s) failed analysis: {failed_articles}")
        
        # Step 2: Sort by importance
        try:
            analyzed_articles.sort(key=lambda x: x.importance_score, reverse=True)
        except (AttributeError, TypeError) as e:
            raise RuntimeError(f"Failed to sort articles by importance: {e}") from e
        
        # Step 3: Allocate time budget using tiered approach
        try:
            analyzed_articles = self._allocate_time_budget(
                analyzed_articles, 
                target_duration, 
                words_per_minute
            )
        except Exception as e:
            raise RuntimeError(f"Failed to allocate time budget: {e}") from e
        
        return analyzed_articles
    
    def _analyze_single_article(
        self, 
        article: Dict[str, Any], 
        idx: int
    ) -> ArticleAnalysis:
        """Analyze a single article"""
        
        if self.use_ai:
            return self._ai_analysis(article, idx)
        else:
            return self._rule_based_analysis(article, idx)
    

    @track(name="research_ai_analysis")
    def _ai_analysis(
        self, 
        article: Dict[str, Any], 
        idx: int
    ) -> ArticleAnalysis:
        """Use GPT to analyze the article"""
        
        # Validate article has required fields
        if not article.get('title') and not article.get('content'):
            print(f"Warning: Article {idx} has no title or content, using rule-based fallback")
            return self._rule_based_analysis(article, idx)
        
        # Load and format prompt
        prompt = prompt_loader.get_user_prompt(
            "research_analyst",
            title=article.get('title', ''),
            content=article.get('content', '')[:1000]
        )
        
        try:
            system_prompt = prompt_loader.get_system_prompt("research_analyst")
            
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                timeout=30.0  # 30 second timeout
            )
            
            if not response or not response.choices:
                raise ValueError("Empty response from OpenAI API")
            
            result = response.choices[0].message.content
            
            if not result:
                raise ValueError("Empty content in OpenAI response")
            
            return self._parse_ai_response(result, article, idx)
            
        except openai.APIError as e:
            print(f"OpenAI API error for article {idx}: {e}. Using rule-based fallback.")
            return self._rule_based_analysis(article, idx)
        except openai.RateLimitError as e:
            print(f"OpenAI rate limit exceeded for article {idx}: {e}. Using rule-based fallback.")
            return self._rule_based_analysis(article, idx)
        except openai.APITimeoutError as e:
            print(f"OpenAI API timeout for article {idx}: {e}. Using rule-based fallback.")
            return self._rule_based_analysis(article, idx)
        except ValueError as e:
            print(f"AI analysis validation error for article {idx}: {e}. Using rule-based fallback.")
            return self._rule_based_analysis(article, idx)
        except Exception as e:
            print(f"Unexpected AI analysis error for article {idx}: {e}. Using rule-based fallback.")
            return self._rule_based_analysis(article, idx)
    
    def _parse_ai_response(
        self, 
        response: str, 
        article: Dict[str, Any], 
        idx: int
    ) -> ArticleAnalysis:
        """Parse GPT response into ArticleAnalysis"""
        
        lines = response.strip().split('\n')
        
        score = 5.0
        category = "other"
        key_points = []
        entities = []
        sentiment = "neutral"
        
        current_section = None
        
        for line in lines:
            line = line.strip()
            if line.startswith("SCORE:"):
                try:
                    score = float(re.search(r'[\d.]+', line).group())
                except:
                    score = 5.0
            elif line.startswith("CATEGORY:"):
                category = line.split(":", 1)[1].strip().lower()
            elif line.startswith("KEY_POINTS:"):
                current_section = "points"
            elif line.startswith("ENTITIES:"):
                entities_str = line.split(":", 1)[1].strip()
                entities = [e.strip() for e in entities_str.split(",")]
                current_section = None
            elif line.startswith("SENTIMENT:"):
                sentiment = line.split(":", 1)[1].strip().lower()
            elif current_section == "points" and line.startswith("-"):
                key_points.append(line[1:].strip())
        
        return ArticleAnalysis(
            article_id=f"article_{idx}",
            title=article.get('title', 'Untitled'),
            content=article.get('content', ''),
            source=article.get('source', 'Unknown'),
            published_date=article.get('published_date', datetime.now().strftime('%Y-%m-%d')),
            importance_score=score,
            category=category,
            key_points=key_points[:3],
            entities=entities[:5],
            sentiment=sentiment,
            time_allocation=0,  # Will be set later
            word_count_target=0,  # Will be set later
            original_word_count=len(article.get('content', '').split())
        )
    
    def _rule_based_analysis(
        self, 
        article: Dict[str, Any], 
        idx: int
    ) -> ArticleAnalysis:
        """Rule-based analysis without AI"""
        
        content = article.get('content', '')
        title = article.get('title', '')
        
        # Simple scoring based on keywords
        breaking_keywords = ['breaking', 'urgent', 'alert', 'just in']
        high_priority_keywords = ['government', 'president', 'crisis', 'emergency']
        
        score = 5.0
        title_lower = title.lower()
        content_lower = content.lower()
        
        if any(kw in title_lower for kw in breaking_keywords):
            score += 3
        if any(kw in content_lower for kw in high_priority_keywords):
            score += 2
        
        # Simple category detection
        category = self._detect_category(title + " " + content)
        
        # Extract first 3 sentences as key points
        sentences = content.split('.')[:3]
        key_points = [s.strip() for s in sentences if s.strip()]
        
        return ArticleAnalysis(
            article_id=f"article_{idx}",
            title=title,
            content=content,
            source=article.get('source', 'Unknown'),
            published_date=article.get('published_date', datetime.now().strftime('%Y-%m-%d')),
            importance_score=min(score, 10.0),
            category=category,
            key_points=key_points,
            entities=[],
            sentiment="neutral",
            time_allocation=0,
            word_count_target=0,
            original_word_count=len(content.split())
        )
    
    def _detect_category(self, text: str) -> str:
        """Simple category detection"""
        text_lower = text.lower()
        
        category_keywords = {
            "politics": ["government", "election", "president", "parliament", "minister"],
            "economy": ["economy", "market", "stock", "financial", "trade"],
            "technology": ["technology", "ai", "software", "digital", "tech"],
            "health": ["health", "medical", "hospital", "disease", "treatment"],
            "sports": ["sports", "game", "match", "player", "championship"],
            "entertainment": ["movie", "music", "celebrity", "entertainment"]
        }
        
        scores = {}
        for category, keywords in category_keywords.items():
            scores[category] = sum(1 for kw in keywords if kw in text_lower)
        
        if scores:
            return max(scores, key=scores.get) if max(scores.values()) > 0 else "other"
        return "other"
    
    def _allocate_time_budget(
        self, 
        articles: List[ArticleAnalysis], 
        target_duration: int,
        words_per_minute: int
    ) -> List[ArticleAnalysis]:
        """
        Allocate time budget using tiered approach that fills the target duration
        
        Tier 1 (Top 20%): Gets proportionally more time
        Tier 2 (Next 30%): Gets medium time
        Tier 3 (Remaining 50%): Gets proportionally less time
        """
        
        total_articles = len(articles)
        
        # Reserve time for intro/outro/transitions (10% of total duration)
        buffer_time = max(20, int(target_duration * 0.1))
        available_time = target_duration - buffer_time
        
        # Calculate tier sizes
        tier1_count = max(1, int(total_articles * 0.2))
        tier2_count = max(1, int(total_articles * 0.3))
        tier3_count = total_articles - tier1_count - tier2_count
        
        # Proportional weights for tiers (tier1 gets 3x more than tier3)
        tier1_weight = 3.0
        tier2_weight = 2.0
        tier3_weight = 1.0
        
        # Calculate total weight
        total_weight = (tier1_count * tier1_weight + 
                       tier2_count * tier2_weight + 
                       tier3_count * tier3_weight)
        
        # Allocate time proportionally to fill the available duration
        tier1_time = int((available_time * tier1_weight) / total_weight) if tier1_count > 0 else 0
        tier2_time = int((available_time * tier2_weight) / total_weight) if tier2_count > 0 else 0
        tier3_time = int((available_time * tier3_weight) / total_weight) if tier3_count > 0 else 0
        
        # Assign time allocations
        for idx, article in enumerate(articles):
            if idx < tier1_count:
                article.time_allocation = tier1_time
                article.urgency = "high"
            elif idx < tier1_count + tier2_count:
                article.time_allocation = tier2_time
                article.urgency = "normal"
            else:
                article.time_allocation = tier3_time
                article.urgency = "low"
            
            # Calculate word count target (accounting for speaking rate)
            words_per_second = words_per_minute / 60
            article.word_count_target = int(article.time_allocation * words_per_second)
        
        return articles
    
    def get_analysis_summary(self, articles: List[ArticleAnalysis]) -> Dict[str, Any]:
        """Generate a summary of the analysis"""
        
        total_time = sum(a.time_allocation for a in articles)
        category_dist = Counter(a.category for a in articles)
        
        return {
            "total_articles": len(articles),
            "total_allocated_time": total_time,
            "category_distribution": dict(category_dist),
            "tier_breakdown": {
                "tier1_high": sum(1 for a in articles if a.urgency == "high"),
                "tier2_medium": sum(1 for a in articles if a.urgency == "normal"),
                "tier3_low": sum(1 for a in articles if a.urgency == "low")
            },
            "average_importance": sum(a.importance_score for a in articles) / len(articles) if articles else 0.0
        }

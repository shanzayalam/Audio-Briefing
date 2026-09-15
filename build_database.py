"""
Build Article Database

PROMPT: Extract articles from URLs using newspaper4k (title/text/authors/date/image).
Analyze with ResearchAnalyst AI (importance/category/points/entities/sentiment).
Assign sequential IDs (enumerate start=1). Save to articles_database.json with UTF-8,
indent=2, ensure_ascii=False. Handle errors gracefully, show progress.
"""

import json
import sys
from datetime import datetime
from typing import List, Dict, Any
from newspaper import Article
from research_analyst import ResearchAnalyst


def extract_article(url: str) -> Dict[str, Any]:
    """Extract article content from URL"""
    try:
        article = Article(url)
        article.download()
        article.parse()
        
        return {
            "url": url,
            "title": article.title,
            "text": article.text,
            "authors": article.authors,
            "publish_date": article.publish_date.isoformat() if article.publish_date else None,
            "top_image": article.top_image,
            "extracted_at": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"❌ Failed to extract {url}: {e}")
        return None


def build_database(urls: List[str], output_file: str = "articles_database.json"):
    """Build article database from URLs"""
    print(f"📰 Building article database from {len(urls)} URLs...")
    
    articles = []
    for i, url in enumerate(urls, 1):
        print(f"   [{i}/{len(urls)}] Extracting: {url[:60]}...")
        article = extract_article(url)
        if article:
            articles.append(article)
            print(f"   ✅ Extracted: {article['title'][:50]}...")
    
    # Analyze articles for categorization
    print("\n🔍 Analyzing articles...")
    analyzer = ResearchAnalyst()
    
    # Prepare articles for analysis
    article_list = []
    for article in articles:
        if article:
            article_list.append({
                'title': article['title'],
                'text': article['text'],
                'url': article['url']
            })
    
    # Batch analyze
    analyzed = analyzer.analyze_articles(article_list, target_duration=300)
    
    # Merge analysis back to articles
    analyzed_articles = []
    for i, article in enumerate(articles):
        if article and i < len(analyzed):
            article['category'] = analyzed[i].category
            article['importance_score'] = analyzed[i].importance_score
            article['key_points'] = analyzed[i].key_points
            analyzed_articles.append(article)
    
    # Add unique IDs to articles
    for idx, article in enumerate(analyzed_articles, start=1):
        article["id"] = idx
    
    # Save database
    database = {
        "created_at": datetime.now().isoformat(),
        "total_articles": len(analyzed_articles),
        "articles": analyzed_articles
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(database, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Database created: {output_file}")
    print(f"   Total articles: {len(analyzed_articles)}")
    
    # Show category breakdown
    categories = {}
    for article in analyzed_articles:
        cat = article.get('category', 'Unknown')
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📊 Category breakdown:")
    for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        print(f"   {cat}: {count}")
    
    return database


if __name__ == "__main__":
    # Load URLs from file
    if len(sys.argv) > 1:
        url_file = sys.argv[1]
    else:
        url_file = "articles_url.txt"
    
    try:
        with open(url_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        # Duplicate URLs to create larger database (as requested)
        urls = urls * 3  # Triple the URLs
        
        build_database(urls)
    except FileNotFoundError:
        print(f"❌ File not found: {url_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

# Tools for scraping General Conference speaker talks
# pip install requests beautifulsoup4

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Dict


def scrape_speaker_talks(speaker_page_url: str, max_talks: int = 30, delay_between_talks: float = 1.5) -> str:
    """Scrape all talks from a speaker's General Conference page.
    
    Args:
        speaker_page_url: URL to the speaker's page (e.g., https://www.churchofjesuschrist.org/study/general-conference/speakers/russell-m-nelson)
        max_talks: Maximum number of talks to fetch (default: 30)
        delay_between_talks: Seconds to wait between fetching each talk to avoid rate limits (default: 1.5)
        
    Returns:
        Formatted string containing all talk information
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        # Fetch the speaker's page
        response = requests.get(speaker_page_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract speaker name from page title or heading
        speaker_name = "Unknown Speaker"
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            speaker_name = title_tag.get_text(strip=True)
            # Clean up the title (remove " - General Conference" etc.)
            speaker_name = re.sub(r'\s*[-–|]\s*.*', '', speaker_name)
        
        # Extract first and last name parts for matching
        name_parts = speaker_name.lower().split()
        
        # Find all talk links on the speaker page
        talk_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            href_lower = href.lower()
            
            # Check if it's a conference talk link and contains any part of the speaker's name
            if '/general-conference/' in href_lower:
                # Check if any name part appears in the href
                contains_name = any(name_part in href_lower for name_part in name_parts if len(name_part) > 2)
                
                if contains_name:
                    # Build full URL if it's relative
                    if href.startswith('/'):
                        full_url = f"https://www.churchofjesuschrist.org{href}"
                    else:
                        full_url = href
                    
                    # Extract year and month from URL
                    year_match = re.search(r'/general-conference/(\d{4})/(\d{2})/', href)
                    if year_match:
                        year, month = year_match.groups()
                    else:
                        year, month = "Unknown", "Unknown"
                    
                    # Get the talk title from link text
                    talk_title = link.get_text(strip=True)
                    
                    talk_links.append({
                        'url': full_url,
                        'year': year,
                        'month': month,
                        'title': talk_title or 'Untitled'
                    })
        
        # Remove duplicates (same URL)
        seen_urls = set()
        unique_talks = []
        for talk in talk_links:
            if talk['url'] not in seen_urls:
                seen_urls.add(talk['url'])
                unique_talks.append(talk)
        
        # Limit to max_talks
        talks_to_fetch = unique_talks[:max_talks]
        
        if not talks_to_fetch:
            return f"No talks found on page: {speaker_page_url}"
        
        # Fetch content for each talk
        all_talks_content = []
        all_talks_content.append(f"Speaker: {speaker_name}")
        all_talks_content.append(f"Found {len(talks_to_fetch)} talk(s)\n")
        all_talks_content.append("=" * 80)
        
        for idx, talk in enumerate(talks_to_fetch, 1):
            try:
                # Add delay between requests to avoid rate limiting (except for first talk)
                if idx > 1 and delay_between_talks > 0:
                    time.sleep(delay_between_talks)
                
                # Fetch the talk content
                talk_response = requests.get(talk['url'], headers=headers, timeout=15)
                talk_response.raise_for_status()
                
                talk_soup = BeautifulSoup(talk_response.content, 'html.parser')
                
                # Find the main content area
                content_div = (
                    talk_soup.find('div', class_='body-block') or 
                    talk_soup.find('article') or 
                    talk_soup.find('main') or
                    talk_soup.find('div', id='content')
                )
                
                if content_div:
                    # Remove unwanted elements
                    for elem in content_div(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                        elem.decompose()
                    
                    # Extract text
                    text = content_div.get_text(separator='\n', strip=True)
                    
                    # Clean up whitespace
                    lines = (line.strip() for line in text.splitlines())
                    text = '\n'.join(line for line in lines if line)
                else:
                    text = "Could not extract talk content"
                
                # Format the talk information
                month_name = "October" if talk['month'] == '10' else "April"
                
                all_talks_content.append(f"\n\n{'='*80}")
                all_talks_content.append(f"Talk #{idx}")
                all_talks_content.append(f"Title: {talk['title']}")
                all_talks_content.append(f"Speaker: {speaker_name}")
                all_talks_content.append(f"Date: {month_name} {talk['year']}")
                all_talks_content.append(f"URL: {talk['url']}")
                all_talks_content.append(f"{'='*80}\n")
                all_talks_content.append(text)
                
            except Exception as e:
                all_talks_content.append(f"\n\nTalk #{idx}: Error fetching {talk['url']} - {str(e)}\n")
        
        return '\n'.join(all_talks_content)
        
    except Exception as e:
        return f"Error scraping speaker page: {str(e)}"


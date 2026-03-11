"""
Tools for General Conference quote finding.
Adapted from lecture2d tools.
"""

import json
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


def fetch_url_content(url: str, timeout: int = 10) -> str:
    """Fetch content from a URL and extract text without HTML tags.
    
    Args:
        url: The URL to fetch content from
        timeout: Maximum time to wait for response in seconds (default: 10)
    
    Returns:
        Extracted text content from the URL
    """
    # Validate URL and protocol
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Unsupported protocol: {parsed.scheme}. Only http and https are allowed.")
        if not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")
    except Exception as e:
        raise ValueError(f"Invalid URL format: {url}") from e
    
    # Set headers to mimic a real browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        
        if 'text/html' in content_type:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(['script', 'style', 'nav', 'header', 'footer']):
                script.decompose()
            
            text = soup.get_text(separator='\n', strip=True)
            
            # Clean up excessive whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text
        else:
            return response.text
            
    except requests.Timeout:
        raise requests.RequestException(f"Request timed out after {timeout} seconds")
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch URL: {str(e)}") from e


def scrape_speaker_talks(speaker_page_url: str, max_talks: int = 200) -> str:
    """Scrape all talks from a speaker's General Conference page.
    
    Args:
        speaker_page_url: URL to the speaker's page
        max_talks: Maximum number of talks to fetch (default: 200)
        
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
            speaker_name = re.sub(r'\s*[-–|]\s*.*', '', speaker_name)
        
        # Extract first and last name parts for matching
        name_parts = speaker_name.lower().split()
        
        # Find all talk links on the speaker page
        # Since we're on the speaker's dedicated page, ALL general-conference links should be theirs
        talk_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            href_lower = href.lower()
            
            # Look for general conference talk URLs (not the speakers index page itself)
            if '/general-conference/' in href_lower and '/speakers/' not in href_lower:
                # Extract year/month from URL to verify it's a specific talk
                year_match = re.search(r'/general-conference/(\d{4})/(\d{2})/', href)
                if year_match:
                    year, month = year_match.groups()
                    
                    # Normalize URL: extract path and rebuild with correct domain
                    # This handles both relative paths and potentially malformed full URLs
                    if href.startswith('http'):
                        # Extract just the path from full URL
                        path_match = re.search(r'https?://[^/]+(/.*)', href)
                        path = path_match.group(1) if path_match else href
                    elif href.startswith('/'):
                        path = href
                    else:
                        path = '/' + href
                    
                    full_url = f"https://www.churchofjesuschrist.org{path}"
                    
                    talk_title = link.get_text(strip=True)
                    
                    talk_links.append({
                        'url': full_url,
                        'year': year,
                        'month': month,
                        'title': talk_title or 'Untitled'
                    })
        
        # Remove duplicates
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
                # Add delay between requests
                if idx > 1:
                    time.sleep(1.5)
                
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
                    for elem in content_div(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                        elem.decompose()
                    
                    text = content_div.get_text(separator='\n', strip=True)
                    lines = (line.strip() for line in text.splitlines())
                    text = '\n'.join(line for line in lines if line)
                else:
                    text = "Could not extract talk content"
                
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


def get_speaker_talk_urls(speaker_page_url: str, max_talks: int = 200) -> str:
    """Get a list of talk URLs from a speaker's General Conference page without fetching full content.
    
    Args:
        speaker_page_url: URL to the speaker's page
        max_talks: Maximum number of talk URLs to return (default: 200)
        
    Returns:
        JSON string with list of talk metadata (title, URL, date)
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
        
        # Extract speaker name
        speaker_name = "Unknown Speaker"
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            speaker_name = title_tag.get_text(strip=True)
            speaker_name = re.sub(r'\s*[-–|]\s*.*', '', speaker_name)
        
        # Extract first and last name parts for matching
        name_parts = speaker_name.lower().split()
        
        # Find all talk links
        # Since we're on the speaker's dedicated page, ALL general-conference links should be theirs
        talk_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            href_lower = href.lower()
            
            # Look for general conference talk URLs (not the speakers index page itself)
            if '/general-conference/' in href_lower and '/speakers/' not in href_lower:
                # Extract year/month from URL to verify it's a specific talk
                year_match = re.search(r'/general-conference/(\d{4})/(\d{2})/', href)
                if year_match:
                    year, month = year_match.groups()
                    
                    # Normalize URL: extract path and rebuild with correct domain
                    # This handles both relative paths and potentially malformed full URLs
                    if href.startswith('http'):
                        # Extract just the path from full URL
                        path_match = re.search(r'https?://[^/]+(/.*)', href)
                        path = path_match.group(1) if path_match else href
                    elif href.startswith('/'):
                        path = href
                    else:
                        path = '/' + href
                    
                    full_url = f"https://www.churchofjesuschrist.org{path}"
                    
                    month_name = "October" if month == '10' else "April"
                    date = f"{month_name} {year}"
                    
                    talk_title = link.get_text(strip=True)
                    
                    talk_links.append({
                        'url': full_url,
                        'title': talk_title or 'Untitled',
                        'date': date
                    })
        
        # Remove duplicates
        seen_urls = set()
        unique_talks = []
        for talk in talk_links:
            if talk['url'] not in seen_urls:
                seen_urls.add(talk['url'])
                unique_talks.append(talk)
        
        # Limit to max_talks
        talks = unique_talks[:max_talks]
        
        result = {
            "speaker": speaker_name,
            "talk_count": len(talks),
            "talks": talks
        }
        
        return json.dumps(result)
        
    except Exception as e:
        return json.dumps({"error": f"Error fetching talk URLs: {str(e)}", "speaker": "", "talk_count": 0, "talks": []})

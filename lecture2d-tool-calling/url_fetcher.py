# Before running this script:
# pip install requests beautifulsoup4

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def fetch_url_content(url: str, timeout: int = 10) -> str:
    """Fetch content from a URL and extract text without HTML tags.
    
    Args:
        url: The URL to fetch content from
        timeout: Maximum time to wait for response in seconds (default: 10)
    
    Returns:
        Extracted text content from the URL
        
    Raises:
        ValueError: If URL is invalid or uses an unsupported protocol
        requests.RequestException: If the HTTP request fails
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
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        # Make the HTTP GET request with timeout
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        
        # Raise an exception for bad status codes (4xx, 5xx)
        response.raise_for_status()
        
        # Check content type
        content_type = response.headers.get('Content-Type', '').lower()
        
        # If it's HTML, parse and extract text
        if 'text/html' in content_type:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(['script', 'style', 'nav', 'header', 'footer']):
                script.decompose()
            
            # Get text content
            text = soup.get_text(separator='\n', strip=True)
            
            # Clean up excessive whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text
        
        # For non-HTML content (plain text, JSON, etc.), return as-is
        else:
            return response.text
            
    except requests.Timeout:
        raise requests.RequestException(f"Request timed out after {timeout} seconds")
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch URL: {str(e)}") from e

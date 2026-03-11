"""
General Conference Quote Finder using multi-agent workflow.
Demonstrates sequential agent orchestration for finding quotes from GC talks using speaker-specific scraping.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent
from tools import ToolBox
from usage import print_usage
from gc_tools import fetch_url_content, scrape_speaker_talks, get_speaker_talk_urls

# Initialize toolbox and register custom tools
toolbox = ToolBox()
toolbox.tool(fetch_url_content)
toolbox.tool(scrape_speaker_talks)
toolbox.tool(get_speaker_talk_urls)


def _parse_json(label: str, text: str) -> dict:
    """Parse JSON from agent output with error handling."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Try to extract JSON object from text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                print(f"ERROR: {label} did not return valid JSON.", file=sys.stderr)
                print(f"Raw output:\n{text}\n", file=sys.stderr)
                raise e
        else:
            raise e
    
    if not isinstance(data, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return data


async def main(agent_config: Path):
    client = AsyncOpenAI()
    config = yaml.safe_load(agent_config.read_text())
    agents = {agent['name']: agent for agent in config['agents']}

    usage = []

    # Get user query
    print("What General Conference quote would you like to find?")
    print("(e.g., 'Find Uchtdorf's talk about adventure in 2019')")
    print("(e.g., 'What did President Nelson say about joy?')")
    query = input(">>> ").strip()
    
    if not query:
        print("No query provided.")
        return

    # Phase 1: Parse the query to extract search parameters
    print("\n-------<analyzing query>-------")
    parser_raw = await run_agent(
        client, toolbox, agents['query_parser'],
        query, [], usage
    )
    parsed = _parse_json("query_parser", parser_raw)
    
    speaker_name = parsed.get("speaker_name")
    topic = parsed.get("topic")
    time_period = parsed.get("time_period")
    keywords = parsed.get("quote_keywords", [])
    summary = parsed.get("summary", "")
    
    print(f"Understood: {summary}")
    if speaker_name:
        print(f"  Speaker: {speaker_name}")
    if topic:
        print(f"  Topic: {topic}")
    if time_period:
        print(f"  Time: {time_period}")
    
    # Phase 1.5: Check if we need clarification
    print("\n-------<checking if clarification needed>-------")
    clarifier_input = json.dumps({
        "parsed_query": parsed
    })
    clarifier_raw = await run_agent(
        client, toolbox, agents['clarifier'],
        clarifier_input, [], usage
    )
    clarification = _parse_json("clarifier", clarifier_raw)
    
    needs_clarification = clarification.get("needs_clarification", False)
    
    if needs_clarification:
        questions = clarification.get("questions", [])
        reason = clarification.get("reason", "")
        
        print(f"Need more information: {reason}")
        print()
        
        # Ask each clarifying question
        user_responses = {}
        for idx, question in enumerate(questions):
            print(question)
            answer = input(">>> ").strip()
            if not answer:
                print("No answer provided. Cannot proceed.")
                return
            user_responses[f"question_{idx}"] = {
                "question": question,
                "answer": answer
            }
        
        # Re-parse with the additional information
        print("\n-------<re-analyzing with clarifications>-------")
        combined_query = f"{query}\n\nAdditional information:\n"
        for resp in user_responses.values():
            combined_query += f"- {resp['question']} {resp['answer']}\n"
        
        parser_raw = await run_agent(
            client, toolbox, agents['query_parser'],
            combined_query, [], usage
        )
        parsed = _parse_json("query_parser", parser_raw)
        
        speaker_name = parsed.get("speaker_name")
        topic = parsed.get("topic")
        time_period = parsed.get("time_period")
        keywords = parsed.get("quote_keywords", [])
        summary = parsed.get("summary", "")
        
        print(f"Updated understanding: {summary}")
        if speaker_name:
            print(f"  Speaker: {speaker_name}")
        if topic:
            print(f"  Topic: {topic}")
        if time_period:
            print(f"  Time: {time_period}")
    
    # Final check - make sure we have a speaker name
    if not speaker_name:
        print("\nError: Need a speaker name to search their talks.")
        print("Please try again with a query like: 'Find Russell M. Nelson's talk about joy'")
        return
    
    # Phase 2: Resolve speaker name to URL using web search
    print("\n-------<finding speaker's page URL>-------")
    resolver_input = json.dumps({
        "speaker_name": speaker_name
    })
    
    # Track history to capture web search results
    resolver_history = []
    resolver_raw = await run_agent(
        client, toolbox, agents['speaker_resolver'],
        resolver_input, resolver_history, usage
    )
    resolution = _parse_json("speaker_resolver", resolver_raw)
    
    speaker_url = resolution.get("speaker_url", "")
    confidence = resolution.get("confidence", "unknown")
    search_summary = resolution.get("search_summary", "")
    
    print(f"Found: {speaker_url}")
    print(f"Confidence: {confidence}")
    if search_summary:
        print(f"Note: {search_summary}")
    
    if not speaker_url:
        print("\nError: Could not find speaker's page. Please try a different speaker name.")
        return
    
    # Phase 3: Get list of talk URLs (without fetching full content yet)
    print("\n-------<getting list of talk URLs>-------")
    
    url_fetcher_input = json.dumps({
        "speaker_url": speaker_url,
        "speaker_name": speaker_name
    })
    
    # Track history to capture the URL list
    url_fetcher_history = []
    url_fetcher_raw = await run_agent(
        client, toolbox, agents['talk_url_fetcher'],
        url_fetcher_input, url_fetcher_history, usage
    )
    url_fetch_results = _parse_json("talk_url_fetcher", url_fetcher_raw)
    
    talk_count = url_fetch_results.get("talk_count", 0)
    print(f"Found {talk_count} talk(s)")
    
    # Extract the actual talk list from the tool call history
    talk_list = []
    for item in url_fetcher_history:
        # Handle both Pydantic objects and dictionaries
        if isinstance(item, dict):
            if item.get("type") == "function_call_output" and "output" in item:
                try:
                    tool_output = json.loads(item["output"])
                    if "talks" in tool_output:
                        talk_list = tool_output["talks"]
                        break
                except:
                    continue
        else:
            # It's a Pydantic object
            if hasattr(item, 'type') and item.type == 'function_call_output':
                try:
                    tool_output = json.loads(item.output)
                    if "talks" in tool_output:
                        talk_list = tool_output["talks"]
                        break
                except:
                    continue
    
    if not talk_list:
        print("No talks found to process.")
        return
    
    # Phase 4: Parallel fetch AND search through talks
    print(f"\n-------<parallel fetching and searching {len(talk_list)} talks>-------")
    
    # Configuration for parallel search
    NUM_PARALLEL_AGENTS = 3  # Number of agents to run in parallel
    
    # Split talk URLs into chunks
    def chunk_talks(talks, num_chunks):
        """Split talks into roughly equal chunks."""
        chunk_size = len(talks) // num_chunks + (1 if len(talks) % num_chunks else 0)
        return [talks[i:i + chunk_size] for i in range(0, len(talks), chunk_size)]
    
    talk_chunks = chunk_talks(talk_list, NUM_PARALLEL_AGENTS)
    
    print(f"Splitting across {len(talk_chunks)} parallel agents:")
    for i, chunk in enumerate(talk_chunks):
        print(f"  Agent {i+1}: {len(chunk)} talks")
    
    # Create a fetch+search task for each chunk
    async def fetch_and_search_chunk(chunk_idx, talk_chunk):
        """Run parallel_talk_searcher to fetch AND search a subset of talks."""
        searcher_input = json.dumps({
            "search_criteria": {
                "speaker_name": speaker_name,
                "topic": topic,
                "time_period": time_period,
                "keywords": keywords
            },
            "talk_urls": talk_chunk,
            "chunk_info": f"Processing chunk {chunk_idx + 1} of {len(talk_chunks)} ({len(talk_chunk)} talks)"
        })
        
        # Start with empty history - this agent will fetch its own talks
        searcher_raw = await run_agent(
            client, toolbox, agents['parallel_talk_searcher'],
            searcher_input, [], usage  # Empty history - agent fetches its own content
        )
        return _parse_json("parallel_talk_searcher", searcher_raw)
    
    # Execute all fetch+search tasks in parallel
    all_search_results = await asyncio.gather(
        *[fetch_and_search_chunk(i, chunk) for i, chunk in enumerate(talk_chunks)]
    )
    
    # Combine results from all agents
    all_quotes = []
    total_talks_processed = 0
    for result in all_search_results:
        all_quotes.extend(result.get("quotes_found", []))
        total_talks_processed += result.get("talks_processed", 0)
    
    # Sort by relevance score (highest first)
    all_quotes.sort(key=lambda q: q.get("relevance_score", 0), reverse=True)
    
    # Create combined search results
    search_results = {
        "quotes_found": all_quotes,
        "total_found": len(all_quotes),
        "summary": f"Processed {total_talks_processed} talks across {len(talk_chunks)} parallel agents"
    }
    
    total_found = len(all_quotes)
    print(f"Found {total_found} matching quote(s) across {len(talk_chunks)} parallel searches")
    print(f"Processed {total_talks_processed} total talks")
    
    # Phase 5: Format the final response
    print("\n-------<formatting results>-------\n")
    formatter_input = json.dumps({
        "search_results": search_results,
        "original_query": query,
        "speaker": speaker_name
    })
    
    final_response = await run_agent(
        client, toolbox, agents['formatter'],
        formatter_input, [], usage
    )
    
    # Output the formatted response
    print(final_response)
    print("\n")
    print_usage(agents['query_parser']['model'], usage)


if __name__ == '__main__':
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'gc_quote_finder.yaml'
    asyncio.run(main(Path(config_file)))

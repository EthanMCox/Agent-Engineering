"""
Guardrail Chat with Input and Output Validation
Simple console-based chat with guardrails
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent, as_tool, Agent
from tools import ToolBox
from usage import print_usage

LOG_FORMAT = '%(filename)-10.10s %(levelname)-4.4s %(asctime)s %(message)s'
logger = logging.getLogger(__name__)


class GuardedChatSystem:
    """
    A chat system with both input and output guardrails.
    
    Workflow:
    1. User message → Input Guardrail (detects taboo topics)
    2. If taboo detected, enhance chat prompt with handling instructions
    3. Chat agent responds
    4. Output Guardrail validates response
    5. If invalid, retry with feedback (max 3 attempts)
    """
    
    def __init__(self, client: AsyncOpenAI, agents: dict[str, Agent]):
        self.client = client
        self.toolbox = ToolBox()
        self.agents = agents
        self.chat_history = []
        self.usages = []
        
    async def process_message(self, user_message: str) -> str:
        """Process a user message through the guardrail pipeline."""
        
        print("\n" + "="*60)
        print("[STEP 1: INPUT GUARDRAIL]")
        print("Checking user input for taboo topics...")
        
        # Step 1: Input Guardrail - Check for taboo topics
        logger.info("Running input guardrail...")
        input_check = await run_agent(
            self.client,
            self.toolbox,
            self.agents['input_guardrail'],
            user_message,
            history=None,
            usage=self.usages
        )
        
        print(f"Input guardrail response: {input_check}")
        
        # Parse input guardrail response (format: "TABOO: <topic>" or "SAFE")
        enhanced_instructions = ""
        if input_check and input_check.startswith("TABOO:"):
            taboo_topic = input_check.replace("TABOO:", "").strip()
            logger.info(f"Taboo topic detected: {taboo_topic}")
            print(f"⚠️  TABOO DETECTED: {taboo_topic}")
            print("Enhancing chat prompt with safety instructions...")
            
            # Enhance the chat prompt with additional instructions
            enhanced_instructions = f"\n\nThe user is asking about {taboo_topic}. Politely decline and redirect to other topics."
        else:
            logger.info("No taboo topics detected")
            print("✓ Input is safe, no taboo topics detected")
        
        # Step 2: Chat Agent produces initial response
        print("\n[STEP 2: CHAT AGENT]")
        chat_agent = self.agents['chat'].copy()
        if enhanced_instructions:
            original_prompt = chat_agent.get('prompt', '')
            chat_agent['prompt'] = original_prompt + enhanced_instructions
            print("Using enhanced prompt with safety instructions")
        else:
            print("Using normal prompt")
        
        chat_response = await run_agent(
            self.client,
            self.toolbox,
            chat_agent,
            user_message,
            history=self.chat_history,
            usage=self.usages
        )
        print(f"Chat response: {chat_response[:100]}..." if len(chat_response) > 100 else f"Chat response: {chat_response}")
        
        # Step 3: Output Guardrail - receives initial response, can call chat as tool if invalid
        print("\n[STEP 3: OUTPUT GUARDRAIL]")
        print("Registering chat as a tool for the output guardrail...")
        guardrail_toolbox = ToolBox()
        guardrail_toolbox.tool(as_tool(self.client, self.toolbox, chat_agent, usage=self.usages))
        
        print("Passing response to output guardrail...")
        final_response = await run_agent(
            self.client,
            guardrail_toolbox,
            self.agents['output_guardrail'],
            chat_response,
            history=None,
            usage=self.usages
        )
        
        print("✓ Output guardrail completed")
        print("="*60 + "\n")
        return final_response


async def main(config_path: Path):
    """Simple console-based chat interface"""
    client = AsyncOpenAI()
    config = yaml.safe_load(config_path.read_text())
    agents = {agent['name']: agent for agent in config['agents']}
    
    system = GuardedChatSystem(client, agents)
    
    print("Guardrail Chat System")
    print("=" * 50)
    print("Type your message and press Enter. Leave empty to quit.")
    print()
    
    while True:
        user_message = input("You: ").strip()
        if not user_message:
            break
        
        response = await system.process_message(user_message)
        print(f"Agent: {response}")
        print()
    
    print()
    print_usage(system.usages)


def _configure_logging(debug: bool) -> None:
    local_level = logging.DEBUG if debug else logging.INFO
    format_string = LOG_FORMAT
    logging.basicConfig(
        level=logging.WARNING,
        format=format_string,
        datefmt='%H:%M:%S',
        force=True,
    )
    for logger_name in ('__main__', 'guarded_chat', 'run_agent', 'tools', 'usage'):
        logging.getLogger(logger_name).setLevel(local_level)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Guardrail Chat System')
    parser.add_argument('config', type=Path, nargs='?', default=Path('guardrails.yaml'),
                        help='Path to YAML configuration file')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    _configure_logging(args.debug)
    
    asyncio.run(main(args.config))

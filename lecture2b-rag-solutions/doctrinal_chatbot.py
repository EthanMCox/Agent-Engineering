# Before running this script:
# pip install chromadb openai gradio

import argparse
import asyncio
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
import gradio as gr
from openai import AsyncOpenAI
from pydantic import BaseModel


class QueryClassification(BaseModel):
    """Classification result indicating if query is about General Conference."""
    is_general_conference_related: bool
    confidence: float
    reasoning: str


class QueryRewrite(BaseModel):
    """Rewritten query optimized for semantic search."""
    rewritten_query: str
    reasoning: str


class DoctrinalChatbot:
    def __init__(
        self,
        chroma_dir: str,
        collection_name: str,
        model: str = "gpt-5-nano",
        classifier_model: str = "gpt-5-nano",
        system_prompt: str = "",
        n_results: int = 3,
    ):
        """
        Initialize the doctrinal chatbot.
        
        Args:
            chroma_dir: Path to ChromaDB directory
            collection_name: Name of the ChromaDB collection to query
            model: OpenAI model to use for chat
            classifier_model: Model to use for query classification (default: gpt-5-nano)
            system_prompt: System prompt explaining how to use the context
            n_results: Number of documents to retrieve from ChromaDB
        """
        self._ai = AsyncOpenAI()
        self.model = model
        self.classifier_model = classifier_model
        self.system_prompt = system_prompt
        self.n_results = n_results
        
        # Connect to ChromaDB
        self.client = chromadb.PersistentClient(path=chroma_dir)
        self.collection = self.client.get_collection(name=collection_name)
        
    def _get_whole_documents(self, filenames: list[str]) -> list[str]:
        """Reconstruct whole documents from chunks."""
        whole_docs = []
        for filename in set(filenames):
            got = self.collection.get(
                where={"filename": filename},
                include=["documents", "metadatas"],
            )
            pairs = list(zip(got["documents"], got["metadatas"]))   # type: ignore
            pairs.sort(key=lambda x: x[1]["chunk_index"])   # type: ignore
            full_text = "".join(t for t, _ in pairs)    # type: ignore
            whole_docs.append(full_text)
        return whole_docs
    
    def query_chromadb(self, query: str) -> list[str]:
        """Query ChromaDB and return relevant whole documents."""
        # Find best matching chunks
        results = self.collection.query(
            query_texts=[query],
            n_results=self.n_results,
            include=["metadatas"],  # type: ignore
        )
        
        # Extract filenames and reconstruct whole documents
        filenames = [meta['filename'] for meta in results['metadatas'][0]]                                          # type: ignore
        docs = self._get_whole_documents(filenames)   # type: ignore
        
        return docs
    
    async def classify_query(self, user_question: str) -> QueryClassification:
        """
        Classify if the user's question is related to General Conference.
        Returns structured output with boolean and reasoning.
        """
        classification_prompt = f"""Determine if the following question is asking about information related to General Conference talks from The Church of Jesus Christ of Latter-day Saints.

General Conference topics include: teachings from Church leaders, doctrine, gospel principles, faith, repentance, covenants, temple work, family, personal revelation, scripture study, service, and spiritual guidance.

Question: {user_question}

Respond with:
- is_general_conference_related: true if the question is about General Conference topics, false otherwise
- confidence: a value between 0.0 and 1.0 indicating your confidence
- reasoning: brief explanation of your classification"""

        response = await self._ai.responses.parse(
            model=self.classifier_model,
            input=classification_prompt,
            text_format=QueryClassification
        )
        
        return QueryClassification.model_validate_json(response.output_text)
    
    async def rewrite_query_for_search(self, user_question: str) -> str:
        """
        Rewrite the user's query to be more effective for semantic search/embeddings.
        
        Rules:
        - Keep the core intent and meaning unchanged
        - Don't add information the user didn't ask for
        - Expand abbreviations and clarify ambiguous terms
        - Convert to more searchable/formal phrasing
        - Remove unnecessary filler words
        
        Returns the rewritten query string.
        """
        rewrite_prompt = f"""Rewrite the following query to be more effective for semantic search in a database of General Conference talks.

Guidelines:
1. Keep the core meaning and intent exactly the same
2. Do NOT add information or topics the user didn't ask about
3. Expand common abbreviations (e.g., "JS" → "Joseph Smith", "BOM" → "Book of Mormon")
4. Convert informal language to more formal, searchable terms
5. Clarify ambiguous pronouns or references
6. Remove filler words that don't help with semantic search
7. Make the query clear and specific for finding relevant talks

Original query: {user_question}

Provide:
- rewritten_query: The optimized version of the query
- reasoning: Brief explanation of changes made"""

        response = await self._ai.responses.parse(
            model=self.classifier_model,
            input=rewrite_prompt,
            text_format=QueryRewrite
        )
        
        rewrite_result = QueryRewrite.model_validate_json(response.output_text)
        return rewrite_result.rewritten_query
    
    async def get_response(self, user_question: str) -> str:
        """
        Get a response to the user's question.
        First classifies if the question is about General Conference.
        If yes, uses RAG with ChromaDB. If no, responds as a normal chatbot.
        Each query is independent - no conversation history is maintained.
        """
        # Classify the query first
        classification = await self.classify_query(user_question)
        
        # Build messages based on classification
        messages = []
        
        if classification.is_general_conference_related:
            # Rewrite query for better semantic search
            search_query = await self.rewrite_query_for_search(user_question)
            
            # Use RAG: Query ChromaDB for relevant context with rewritten query
            context_docs = self.query_chromadb(search_query)
            context = "\n\n---\n\n".join(context_docs)
            
            rag_system_prompt = self.system_prompt if self.system_prompt else ""

            rag_system_prompt += """\n\nYou have access to a database of General Conference talks. When a user asks a question, you automatically search the database and retrieve relevant talks. The retrieved talks will be provided to you before the user's question. These are talks you searched for and found, not information the user provided to you. Therefore, you should frame your responses as though you were the one to find and provide the information from the talks, rather than assuming the user provided them. When providing answers, please share the title of the talk and the name of the speaker, along with what they said that addresses the question from the user."""
            
            messages.append({
                'role': 'system',
                'content': rag_system_prompt
            })
            
            # Present context as your retrieval, then the user's question
            messages.append({
                'role': 'assistant',
                'content': f"""[RETRIEVED CONTEXT - These are General Conference talks you found by searching the database]

{context}

[END RETRIEVED CONTEXT]

[USER'S QUESTION]
{user_question}"""
            })
        else:
            # Not General Conference related - respond as normal chatbot
            if self.system_prompt:
                messages.append({
                    'role': 'system',
                    'content': self.system_prompt
                })
            
            messages.append({
                'role': 'user',
                'content': user_question
            })
        
        # Get response from LLM
        response = await self._ai.responses.create(
            input=messages,
            model=self.model
        )
        
        return response.output_text


def main_gradio(chatbot: DoctrinalChatbot):
    """Launch Gradio web interface."""
    css = """
    .gradio-container, .gradio-app, .gradio-root {
      width: 120ch;
      max-width: 120ch !important;
      margin-left: auto !important;
      margin-right: auto !important;
      box-sizing: border-box !important;
    }
    """
    
    with gr.Blocks() as demo:
        gr.Markdown("# General Conference Chatbot")
        gr.Markdown("Ask questions about General Conference talks. Each question is answered independently using relevant talk excerpts.")
        
        async def respond(message, history):
            """Handle user message - history is ignored to keep queries independent."""
            response = await chatbot.get_response(message)
            return response
        
        chat = gr.ChatInterface(
            fn=respond,
            examples=[
                "What did President Oaks say about faith?",
                "How can I strengthen my family?",
                "What counsel was given about the covenant path?",
            ],
            title="",
        )
    
    demo.launch(css=css)


async def main_console(chatbot: DoctrinalChatbot):
    """Run chatbot in console mode."""
    print("General Conference Chatbot")
    print("Ask questions about General Conference talks (press Enter with empty input to quit)\n")
    
    while True:
        question = input('Question: ')
        if not question.strip():
            break
        
        response = await chatbot.get_response(question)
        print(f'\nAnswer: {response}\n')
        print('-' * 80)


def main(
    chroma_dir: str,
    collection: str,
    prompt_file: Optional[Path],
    model: str,
    classifier_model: str,
    n_results: int,
    use_web: bool
):
    """Main entry point."""
    # Load system prompt from file if provided
    system_prompt = ""
    if prompt_file and prompt_file.exists():
        system_prompt = prompt_file.read_text(encoding='utf-8')
    
    # Create chatbot
    chatbot = DoctrinalChatbot(
        chroma_dir=chroma_dir,
        collection_name=collection,
        model=model,
        classifier_model=classifier_model,
        system_prompt=system_prompt,
        n_results=n_results,
    )
    
    # Launch interface
    if use_web:
        main_gradio(chatbot)
    else:
        asyncio.run(main_console(chatbot))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Doctrinal Chatbot for General Conference Talks')
    parser.add_argument(
        '--chroma-dir',
        default='./chroma_db',
        help='Path to ChromaDB directory (default: ./chroma_db)'
    )
    parser.add_argument(
        '--collection',
        default='gc_talks',
        help='ChromaDB collection name (default: gc_talks)'
    )
    parser.add_argument(
        '--prompt-file',
        type=Path,
        default=None,
        help='Path to system prompt file (optional)'
    )
    parser.add_argument(
        '--model',
        default='gpt-5-nano',
        help='OpenAI model to use for chat (default: gpt-5-nano)'
    )
    parser.add_argument(
        '--classifier-model',
        default='gpt-5-nano',
        help='OpenAI model to use for query classification (default: gpt-5-nano)'
    )
    parser.add_argument(
        '--n-results',
        type=int,
        default=3,
        help='Number of talks to retrieve from ChromaDB (default: 3)'
    )
    parser.add_argument(
        '--web',
        action='store_true',
        help='Launch web interface (default: console mode)'
    )
    
    args = parser.parse_args()
    main(
        chroma_dir=args.chroma_dir,
        collection=args.collection,
        prompt_file=args.prompt_file,
        model=args.model,
        classifier_model=args.classifier_model,
        n_results=args.n_results,
        use_web=args.web,
    )

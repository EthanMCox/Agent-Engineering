# Scripture Search with OpenAI File Search Tool

This implementation uses OpenAI's Assistants API with the `file_search` tool to search through the Standard Works.

## Setup

### Step 1: Upload Scripture Files to OpenAI

First, you need to upload your scripture files and create a vector store:

```bash
python setup_scripture_vector_store.py
```

This will:

- Upload all scripture files from `../standard-works`
- Create a vector store with those files
- Save the `vector_store_id` to `scripture_vector_store_id.txt`

**Note:** This will incur storage costs on your OpenAI account (~$0.10/GB/day).

### Step 2: Run the Scripture Assistant

Once you have the vector store ID, run:

```bash
python toolbot_scripture.py --vector-store-id vs_xxxxxxxxxxxxx
```

Or, if you saved the ID to the config file:

```bash
python toolbot_scripture.py --vector-store-id $(cat scripture_vector_store_id.txt)
```

## Usage Example

```bash
# With a system prompt
python toolbot_scripture.py system_prompt.md --vector-store-id vs_xxxxxxxxxxxxx

# With web interface
python toolbot_scripture.py --web --vector-store-id vs_xxxxxxxxxxxxx

# With reasoning display
python toolbot_scripture.py --show-reasoning --vector-store-id vs_xxxxxxxxxxxxx
```

## How It Works

The `toolbot_scripture.py` file uses the **Assistants API** instead of the `responses.create()` API:

1. **Creates an Assistant** with file_search tool enabled
2. **Creates a Thread** for conversation history
3. **Adds Messages** to the thread
4. **Runs the Assistant** with streaming responses
5. **Handles Tool Calls** including file_search automatically

When you ask questions about scriptures, the assistant will:

- Search the vector store semantically
- Retrieve relevant passages
- Cite sources in the response

## Key Differences from Original toolbot.py

| Feature      | toolbot.py           | toolbot_scripture.py           |
| ------------ | -------------------- | ------------------------------ |
| API          | `responses.create()` | Assistants API                 |
| File Search  | Not available        | Built-in with vector stores    |
| Setup        | None                 | Requires vector store creation |
| Cost         | Pay per request      | Pay per request + storage      |
| Conversation | Stateless            | Maintains thread state         |
| Custom Tools | ✓ Supported          | ✓ Supported                    |
| Web Search   | ✓ Supported          | ✗ Not in this version          |

## Example Questions

Try asking:

- "What does the Book of Mormon say about faith?"
- "Find verses about prayer in the New Testament"
- "Compare what Jesus taught in 3 Nephi vs Matthew"
- "What did Isaiah prophesy about Christ?"

## Cleanup

To delete the vector store and files (to stop incurring costs):

```python
from openai import OpenAI
client = OpenAI()

# Delete vector store
client.beta.vector_stores.delete("vs_xxxxxxxxxxxxx")

# Optionally delete individual files
# client.files.delete("file_xxxxx")
```

## Limitations

1. **Token Limits**: File search has a ~20k token context limit
2. **Cost**: Storage fees apply (~$0.10/GB/day)
3. **Upload Time**: Initial setup takes several minutes for all scripture files
4. **No Web Search**: This version doesn't include web_search tool (could be added)
5. **Search Quality**: Depends on OpenAI's vector store implementation

## Alternative: Local RAG

If you prefer to avoid upload costs and storage fees, consider using the local RAG approach with ChromaDB (see lecture2b-rag-solutions). This would:

- Keep all data local
- Have no ongoing costs
- Give you more control over chunking and search
- Work offline

from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper


@tool
def search_tool(query: str) -> str:
    """
    Searches the web for real-time information using DuckDuckGo.
    Use this for current events, news, or facts not in your local database.
    Input: A short, specific natural language search query.
    """
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))

        if not results:
            return f"No results found for '{query}'."

        # Format results into a readable string
        formatted = []
        for r in results:
            title = r.get("title", "No title")
            body  = r.get("body", "No content")
            href  = r.get("href", "")
            formatted.append(f"• {title}\n  {body}\n  Source: {href}")

        return "\n\n".join(formatted)

    except ImportError:
        return "Error: Install ddgs with 'pip install ddgs'"
    except Exception as e:
        return f"Search failed: {str(e)}"
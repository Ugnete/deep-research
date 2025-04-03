from fastapi import FastAPI
from pydantic import BaseModel
import modal
from codegen import Codebase
from langchain_core.messages import SystemMessage
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import List
from fastapi.responses import StreamingResponse
import json
from langchain.agents import AgentExecutor, create_structured_chat_agent
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool

# Modal image configuration
image = (
    modal.Image.debian_slim()
    .apt_install("git")
    .pip_install(
        "codegen==0.52.19",
        "fastapi",
        "uvicorn",
        "langchain",
        "langchain-core",
        "langchain-anthropic",
        "langchain-openai",
        "pydantic",
    )
)

# Modal app configuration
app = modal.App(
    name="code-research-app",
    image=image,
    secrets=[modal.Secret.from_name("agent-secret")],
)

# FastAPI app configuration
fastapi_app = FastAPI()
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Research agent prompt
RESEARCH_AGENT_PROMPT = """You are a code research expert. Your goal is to help users understand codebases by:
Finding relevant code through semantic and text search
Analyzing symbol relationships and dependencies
Exploring directory structures
Reading and explaining code
Always explain your findings in detail and provide context about how different parts of the code relate to each other.
When analyzing code, consider:
- The purpose and functionality of each component
- How different parts interact
- Key patterns and design decisions
- Potential areas for improvement
Break down complex concepts into understandable pieces and use examples when helpful.

{format_instructions}

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question"""

# Global variable to track status
current_status = "Initializing process..."

# Request and response models
class ResearchRequest(BaseModel):
    repo_name: str
    query: str

class ResearchResponse(BaseModel):
    response: str

class FilesResponse(BaseModel):
    files: List[str]

class StatusResponse(BaseModel):
    status: str

def update_status(new_status: str):
    """Update the current status and return a status response object."""
    global current_status
    current_status = new_status
    return {"type": "status", "content": new_status}

def create_research_tools(codebase):
    """Create tools for code research using the codebase."""
    
    @tool
    def view_file(filepath: str) -> str:
        """View the content of a file in the codebase."""
        try:
            file = codebase.get_file(filepath)
            if file:
                return file.content
            return f"File not found: {filepath}"
        except Exception as e:
            return f"Error viewing file: {str(e)}"
    
    @tool
    def list_directory(directory: str = "") -> str:
        """List files and directories in the specified directory."""
        try:
            if directory and not directory.endswith("/"):
                directory += "/"
            
            files = []
            for file in codebase.files:
                if file.filepath.startswith(directory):
                    relative_path = file.filepath[len(directory):] if directory else file.filepath
                    if "/" not in relative_path:
                        files.append(file.filepath)
            
            return "\n".join(files) if files else f"No files found in directory: {directory}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
    
    @tool
    def search_code(query: str) -> str:
        """Search for code patterns in the codebase."""
        try:
            results = []
            for file in codebase.files:
                if query.lower() in file.content.lower():
                    lines = file.content.split("\n")
                    for i, line in enumerate(lines):
                        if query.lower() in line.lower():
                            results.append(f"{file.filepath}:{i+1}: {line.strip()}")
                            if len(results) >= 20:  # Limit results
                                break
                    if len(results) >= 20:
                        break
            
            return "\n".join(results) if results else f"No results found for query: {query}"
        except Exception as e:
            return f"Error searching code: {str(e)}"
    
    @tool
    def semantic_search(query: str) -> str:
        """Perform semantic search on the codebase."""
        try:
            # Simple implementation - in a real app, you'd use embeddings
            results = []
            for file in codebase.files:
                if any(term.lower() in file.content.lower() for term in query.split()):
                    results.append(f"{file.filepath}")
                    if len(results) >= 10:  # Limit results
                        break
            
            return "\n".join(results) if results else f"No semantic results found for query: {query}"
        except Exception as e:
            return f"Error in semantic search: {str(e)}"
    
    @tool
    def reveal_symbol(symbol_name: str) -> str:
        """Find and analyze a symbol (function, class, etc.) in the codebase."""
        try:
            # Simple implementation - in a real app, you'd use codegen's symbol analysis
            results = []
            for file in codebase.files:
                if symbol_name in file.content:
                    results.append(f"Symbol '{symbol_name}' found in {file.filepath}")
                    if len(results) >= 5:  # Limit results
                        break
            
            return "\n".join(results) if results else f"Symbol '{symbol_name}' not found"
        except Exception as e:
            return f"Error revealing symbol: {str(e)}"
    
    return [view_file, list_directory, search_code, semantic_search, reveal_symbol]

def get_llm():
    """Get the appropriate LLM based on available API keys."""
    # Check for Anthropic API key
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ChatAnthropic(temperature=0, model="claude-3-sonnet-20240229", max_tokens=4000)
    
    # Check for OpenAI API key with custom endpoint
    elif os.environ.get("OPENAI_API_KEY"):
        openai_args = {
            "temperature": 0,
            "max_tokens": 4000,
        }
        
        # Use custom endpoint if provided
        if os.environ.get("OPENAI_API_ENDPOINT"):
            openai_args["openai_api_base"] = os.environ.get("OPENAI_API_ENDPOINT")
        
        # Use custom model if provided
        if os.environ.get("OPENAI_MODEL"):
            openai_args["model"] = os.environ.get("OPENAI_MODEL")
        else:
            openai_args["model"] = "gpt-4"
            
        return ChatOpenAI(**openai_args)
    
    # Default to a simple error message if no API keys are available
    else:
        raise ValueError("No API keys found. Please set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment.")

def create_research_agent(codebase):
    """Create a research agent with the given codebase."""
    # Create tools
    tools = create_research_tools(codebase)
    
    # Get tool names for the prompt
    tool_names = [tool.name for tool in tools]
    
    # Get the LLM
    llm = get_llm()
    
    # Create the agent executor
    agent_executor = AgentExecutor.from_agent_and_tools(
        agent=create_structured_chat_agent(
            llm=llm,
            tools=tools,
            prompt=ChatPromptTemplate.from_template(RESEARCH_AGENT_PROMPT),
        ),
        tools=tools,
        verbose=True,
        return_intermediate_steps=True,
    )
    
    return agent_executor

@fastapi_app.post("/research", response_model=ResearchResponse)
async def research(request: ResearchRequest) -> ResearchResponse:
    """
    Endpoint to perform code research on a GitHub repository.
    """
    try:
        update_status("Initializing codebase...")
        codebase = Codebase.from_repo(request.repo_name)

        update_status("Creating research tools...")
        agent = create_research_agent(codebase)

        update_status("Running analysis...")
        result = agent.invoke(
            {"input": request.query, "chat_history": []}
        )

        update_status("Complete")
        return ResearchResponse(response=result["output"])

    except Exception as e:
        update_status("Error occurred")
        return ResearchResponse(response=f"Error during research: {str(e)}")

@fastapi_app.post("/similar-files", response_model=FilesResponse)
async def similar_files(request: ResearchRequest) -> FilesResponse:
    """
    Endpoint to find similar files in a GitHub repository based on a query.
    """
    try:
        codebase = Codebase.from_repo(request.repo_name)
        
        # Simple implementation - in a real app, you'd use embeddings
        similar_files = []
        for file in codebase.files:
            if any(term.lower() in file.content.lower() for term in request.query.split()):
                similar_files.append(file.filepath)
                if len(similar_files) >= 30:  # Expanded to 30 files
                    break
        
        return FilesResponse(files=similar_files)

    except Exception as e:
        update_status("Error occurred")
        return FilesResponse(files=[f"Error finding similar files: {str(e)}"])

@app.function()
async def get_similar_files(repo_name: str, query: str) -> List[str]:
    """
    Separate Modal function to find similar files
    """
    codebase = Codebase.from_repo(repo_name)
    
    # Simple implementation - in a real app, you'd use embeddings
    similar_files = []
    for file in codebase.files:
        if any(term.lower() in file.content.lower() for term in query.split()):
            similar_files.append(file.filepath)
            if len(similar_files) >= 30:  # Expanded to 30 files
                break
    
    return similar_files

@fastapi_app.post("/research/stream")
async def research_stream(request: ResearchRequest):
    """
    Streaming endpoint to perform code research on a GitHub repository.
    """
    try:
        async def event_generator():
            final_response = ""

            similar_files_future = get_similar_files.remote.aio(
                request.repo_name, request.query
            )

            codebase = Codebase.from_repo(request.repo_name)
            agent = create_research_agent(codebase)

            # Get similar files first
            similar_files = await similar_files_future
            yield f"data: {json.dumps({'type': 'similar_files', 'content': similar_files})}\n\n"
            
            # Start the agent execution
            yield f"data: {json.dumps({'type': 'status', 'content': 'Starting agent run'})}\n\n"
            
            # Execute the agent
            result = agent.invoke(
                {"input": request.query, "chat_history": []}
            )
            
            # Send intermediate steps as tool events
            for step in result.get("intermediate_steps", []):
                tool_action = step[0]
                tool_output = step[1]
                
                # Tool start event
                yield f"data: {json.dumps({'type': 'on_tool_start', 'data': {'name': tool_action.tool, 'input': tool_action.tool_input}})}\n\n"
                
                # Tool end event
                yield f"data: {json.dumps({'type': 'on_tool_end', 'data': {'name': tool_action.tool, 'output': tool_output}})}\n\n"
            
            # Stream the final result in chunks
            final_response = result["output"]
            chunk_size = 100
            for i in range(0, len(final_response), chunk_size):
                chunk = final_response[i:i+chunk_size]
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
            
            yield f"data: {json.dumps({'type': 'complete', 'content': final_response})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    except Exception as e:
        error_status = update_status("Error occurred")
        return StreamingResponse(
            iter(
                [
                    f"data: {json.dumps(error_status)}\n\n",
                    f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n",
                ]
            ),
            media_type="text/event-stream",
        )

@app.function(image=image, secrets=[modal.Secret.from_name("agent-secret")])
@modal.asgi_app()
def fastapi_modal_app():
    return fastapi_app

if __name__ == "__main__":
    app.deploy("code-research-app")

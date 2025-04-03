from fastapi import FastAPI
from pydantic import BaseModel
import modal
from codegen import Codebase
from codegen.extensions.langchain.agent import create_agent_with_tools
from langchain_core.messages import SystemMessage
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import List, Optional
from fastapi.responses import StreamingResponse
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
Break down complex concepts into understandable pieces and use examples when helpful."""

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

def get_model_config():
    """Get model configuration from environment variables."""
    # Check for Anthropic API key
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    # Check for OpenAI API key and custom endpoint
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openai_api_endpoint = os.environ.get("OPENAI_API_ENDPOINT")
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4")
    
    # Determine which model provider to use
    if anthropic_api_key:
        logger.info("Using Anthropic Claude model")
        return {
            "model_provider": "anthropic",
            "model_name": "claude-3-sonnet-20240229",
            "anthropic_api_key": anthropic_api_key
        }
    elif openai_api_key:
        logger.info(f"Using OpenAI model: {openai_model}")
        config = {
            "model_provider": "openai",
            "model_name": openai_model,
            "openai_api_key": openai_api_key
        }
        if openai_api_endpoint:
            logger.info(f"Using custom OpenAI API endpoint: {openai_api_endpoint}")
            config["openai_api_base"] = openai_api_endpoint
        return config
    else:
        raise ValueError("No API keys found. Please set either ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment.")

@fastapi_app.post("/research", response_model=ResearchResponse)
async def research(request: ResearchRequest) -> ResearchResponse:
    """
    Endpoint to perform code research on a GitHub repository.
    """
    try:
        update_status("Initializing codebase...")
        codebase = Codebase.from_repo(request.repo_name)

        update_status("Creating research tools...")
        model_config = get_model_config()
        agent = create_agent_with_tools(
            codebase=codebase,
            system_message=SystemMessage(content=RESEARCH_AGENT_PROMPT),
            **model_config,
            verbose=True,
        )

        update_status("Running analysis...")
        result = agent.invoke(
            {"input": request.query, "chat_history": []}
        )

        update_status("Complete")
        return ResearchResponse(response=result["output"])

    except Exception as e:
        logger.error(f"Error during research: {str(e)}", exc_info=True)
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
        logger.error(f"Error finding similar files: {str(e)}", exc_info=True)
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
            try:
                # Initialize codebase
                yield f"data: {json.dumps({'type': 'status', 'content': 'Initializing codebase'})}\n\n"
                codebase = Codebase.from_repo(request.repo_name)
                
                # Get similar files
                yield f"data: {json.dumps({'type': 'status', 'content': 'Finding similar files'})}\n\n"
                similar_files = []
                for file in codebase.files:
                    if any(term.lower() in file.content.lower() for term in request.query.split()):
                        similar_files.append(file.filepath)
                        if len(similar_files) >= 30:
                            break
                
                yield f"data: {json.dumps({'type': 'similar_files', 'content': similar_files})}\n\n"
                
                # Create agent
                yield f"data: {json.dumps({'type': 'status', 'content': 'Creating research agent'})}\n\n"
                model_config = get_model_config()
                agent = create_agent_with_tools(
                    codebase=codebase,
                    system_message=SystemMessage(content=RESEARCH_AGENT_PROMPT),
                    **model_config,
                    verbose=True,
                )
                
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
            
            except Exception as e:
                logger.error(f"Error in event generator: {str(e)}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    except Exception as e:
        logger.error(f"Error in research_stream: {str(e)}", exc_info=True)
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

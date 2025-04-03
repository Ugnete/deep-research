"use client"

import { useState, useEffect } from "react"
import { Github, ArrowRight, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import ReactMarkdown from 'react-markdown'

const MODAL_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function formatToolEvent(eventData) {
  if (!eventData) return "Tool event data missing";
  
  try {
    const { name, input, output } = eventData;
    if (name && input) {
      return `Using tool: ${name} with input: ${typeof input === 'string' ? input : JSON.stringify(input)}`;
    } else if (name && output) {
      const displayOutput = typeof output === 'string' && output.length > 150 
        ? output.substring(0, 150) + "..." 
        : output;
      return `Tool ${name} returned: ${typeof displayOutput === 'string' ? displayOutput : JSON.stringify(displayOutput)}`;
    }
    return JSON.stringify(eventData);
  } catch (e) {
    console.error('Error formatting tool event:', e);
    return JSON.stringify(eventData);
  }
}

export default function RepoChatDashboard() {
  const [repoUrl, setRepoUrl] = useState("")
  const [question, setQuestion] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isLandingPage, setIsLandingPage] = useState(true)
  const [researchResult, setResearchResult] = useState<string>("")
  const [showQueryInput, setShowQueryInput] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [similarFiles, setSimilarFiles] = useState<string[]>([])
  const [errorMessage, setErrorMessage] = useState<string>("")

  useEffect(() => {
    if (repoUrl) {
      setShowQueryInput(true)
    } else {
      setShowQueryInput(false)
    }
  }, [repoUrl])

  const parseRepoUrl = (input: string): string => {
    try {
      if (input.includes('github.com')) {
        const url = new URL(input)
        const pathParts = url.pathname.split('/').filter(Boolean)
        if (pathParts.length >= 2) {
          return `${pathParts[0]}/${pathParts[1]}`
        }
      }
      if (input.includes('/') && !input.includes(' ')) {
        const parts = input.split('/')
        if (parts.length === 2) {
          return input
        }
      }
    } catch (e) {
      console.error('Error parsing URL:', e)
    }
    return input
  }

  const handleSubmit = async () => {
    if (!repoUrl) {
      setErrorMessage('Please enter a repository URL');
      return;
    }
    if (!question) {
      setErrorMessage('Please enter a question about the codebase');
      return;
    }
    
    setErrorMessage("");
    setIsLoading(true);
    setIsLandingPage(false);
    setResearchResult("");
    setLogs([]);
    setSimilarFiles([]);
    
    setLogs(["Fetching codebase"]);
    await new Promise(resolve => setTimeout(resolve, 2000));
    
    setLogs(prev => [...prev, "Initializing research tools for agent"]);
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    try {
      const parsedRepoUrl = parseRepoUrl(repoUrl);
      
      setLogs(prev => [...prev, "Looking through files"]);
      
      const response = await fetch(`${MODAL_API_URL}/research/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          repo_name: parsedRepoUrl,
          query: question
        })
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch research results: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Failed to get response reader');
      }

      const decoder = new TextDecoder();
      let partialLine = '';

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          const chunk = partialLine + decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');
          
          partialLine = lines[lines.length - 1];

          for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i].trim();
            if (line.startsWith('data: ')) {
              try {
                const eventData = JSON.parse(line.slice(6));
                switch (eventData.type) {
                  case 'similar_files':
                    setSimilarFiles(eventData.content);
                    setLogs(prev => [...prev, "Starting agent run"]);
                    break;
                  case 'status':
                    setLogs(prev => [...prev, eventData.content]);
                    break;
                  case 'content':
                    setResearchResult(prev => prev + eventData.content);
                    break;
                  case 'error':
                    setResearchResult(`Error: ${eventData.content}`);
                    setErrorMessage(`Error: ${eventData.content}`);
                    setIsLoading(false);
                    return;
                  case 'complete':
                    setResearchResult(eventData.content);
                    setLogs(prev => [...prev, "Analysis complete"]);
                    setIsLoading(false);
                    return;
                  case 'on_tool_start':
                    setLogs(prev => [...prev, formatToolEvent(eventData.data)]);
                    break;
                  case 'on_tool_end':
                    setLogs(prev => [...prev, formatToolEvent(eventData.data)]);
                    break;
                  default:
                    console.log('Unknown event type:', eventData.type);
                }
              } catch (e) {
                console.error('Error parsing event:', e, line);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      console.error('Error:', error);
      setErrorMessage(error.message || "Failed to process request. Please try again.");
      setResearchResult("Error: Failed to process request. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSubmit();
    }
  }

  const resetSearch = () => {
    setIsLandingPage(true);
    setErrorMessage("");
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-black to-black text-foreground">
      <div className={`absolute w-full transition-all duration-300 ease-in-out
        ${isLandingPage 
          ? 'opacity-100 translate-y-0' 
          : 'opacity-0 translate-y-0 pointer-events-none'}`}>
        <div className={`flex flex-col items-center justify-center min-h-screen p-4 
          transition-all duration-300 ease-in-out
          ${isTransitioning ? 'opacity-0' : 'opacity-100'}`}>
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold flex items-center justify-center gap-3 mb-4 text-white">
              <img src="cg.png" alt="CG Logo" className="h-12 w-12" />
              <span>Deep Research</span>
            </h1>
            <p className="text-muted-foreground">
              Unlock the power of <a href="https://codegen.com" target="_blank" rel="noopener noreferrer" className="hover:text-primary">Codegen</a> in codebase exploration.
            </p>
          </div>
          <div className="flex flex-col gap-3 w-full max-w-xl px-8">
            <Input
              type="text"
              placeholder="GitHub repo link or owner/repo"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              className="flex-1 h-25 text-lg px-4 mb-2 bg-[#050505] text-muted-foreground"
              title="Format: https://github.com/owner/repo or owner/repo"
            />
            <div
              className={`transition-all duration-500 ease-in-out ${
                showQueryInput ? 'max-h-40 opacity-100' : 'max-h-0 opacity-0'
              }`}
            >
              <Input
                type="text"
                placeholder="Ask Deep Research anything about the codebase"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyPress={handleKeyPress}
                className="flex-1 h-25 text-lg px-4 mb-2 bg-[#050505] text-muted-foreground"
              />
            </div>
            {errorMessage && (
              <div className="text-red-500 text-sm mt-1 mb-2">{errorMessage}</div>
            )}
            <div className="flex justify-center">
              <Button 
                onClick={handleSubmit} 
                disabled={isLoading}
                className="w-32 mt-5"
              >
                <span className="font-semibold flex items-center gap-2">
                  {isLoading ? "Loading..." : <>Explore <ArrowRight className="h-4 w-4" /></>}
                </span>
              </Button>
            </div>
          </div>
        </div>
      </div>
      <div className={`w-full flex-1 transition-all duration-300 ease-in-out
        ${!isLandingPage 
          ? 'opacity-100 translate-y-0' 
          : 'opacity-0 translate-y-0 pointer-events-none'}`}>
        <div className={`flex-1 px-10 space-y-4 py-8 pt-8 max-w-[1400px] mx-auto
          transition-all duration-300 ease-in-out
          ${isTransitioning ? 'opacity-0' : 'opacity-100'}`}>
          <div className="flex items-center justify-between space-x-4">
            <div 
              className="flex items-center gap-3 cursor-pointer hover:opacity-80" 
              onClick={resetSearch}
            >
              <img src="cg.png" alt="CG Logo" className="h-8 w-8" />
              <h2 className="text-3xl font-bold tracking-tight">Deep Research</h2>
            </div>
            <Button onClick={resetSearch}>
              <span className="font-semibold">New Search</span>
            </Button>
          </div>
          <br></br>
          <div className="min-h-[calc(100vh-12rem)] animate-in fade-in slide-in-from-bottom-4 duration-500 fill-mode-forwards [animation-delay:600ms]">
            <Card className="h-full border-0">
              <CardHeader>
                <CardTitle className="text-2xl">{question || "No query provided"}</CardTitle>
                <div className="flex items-center gap-2 text-md text-muted-foreground">
                  <Github className="h-4 w-4" />
                  <a 
                    href={`https://github.com/${parseRepoUrl(repoUrl)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    {parseRepoUrl(repoUrl)}
                  </a>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-6">
                  {isLoading && !researchResult && (
                    <div className="animate-pulse flex space-x-4">
                      <div className="flex-1 space-y-4 py-1">
                        <div className="h-4 bg-muted/50 rounded w-3/4"></div>
                        <div className="space-y-2">
                          <div className="h-4 bg-muted/50 rounded"></div>
                          <div className="h-4 bg-muted/50 rounded w-5/6"></div>
                        </div>
                      </div>
                    </div>
                  )}
                  
                  {researchResult && (
                    <div className="space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-500">
                      <Card className="bg-muted/25 border-none rounded-xl">
                        <CardContent className="pt-6 prose prose-sm max-w-none">
                          <ReactMarkdown className="text-white text-md">{researchResult}</ReactMarkdown>
                        </CardContent>
                      </Card>
                    </div>
                  )}

                  {(researchResult || isLoading) && (
                    <div className="space-y-3">
                      <h3 className="text-lg font-semibold">Relevant Files</h3>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {isLoading && !similarFiles.length ? (
                          Array(3).fill(0).map((_, i) => (
                            <Card 
                              key={i} 
                              className="h-24 flex items-center justify-center bg-muted/25 border-none rounded-xl"
                            >
                              <p className="text-sm text-muted-foreground">Loading...</p>
                            </Card>
                          ))
                        ) : similarFiles.length > 0 ? (
                          similarFiles.map((file, i) => {
                            const fileName = file.split('/').pop() || file;
                            const filePath = file.split('/').slice(0, -1).join('/');
                            return (
                              <Card 
                                key={i} 
                                className="p-4 flex flex-col justify-between bg-muted/25 border-none hover:bg-muted transition-colors cursor-pointer rounded-xl animate-in fade-in slide-in-from-bottom-2 duration-500"
                                style={{ animationDelay: `${i * 100}ms` }}
                                onClick={() => window.open(`https://github.com/${parseRepoUrl(repoUrl)}/blob/main/${file}`, '_blank')}
                              >
                                <div className="flex flex-col gap-2">
                                  <div className="flex items-center gap-2">
                                    <FileText className="h-4 w-4 flex-shrink-0" />
                                    <div>
                                      <p className="text-sm font-medium break-words">{fileName}</p>
                                      {filePath && (
                                        <p className="text-xs text-muted-foreground break-words">{filePath}</p>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </Card>
                            );
                          })
                        ) : (
                          <div className="col-span-3 text-center text-muted-foreground py-4">
                            No relevant files found.
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="space-y-3">
                    <h3 className="text-lg font-semibold">Agent Logs</h3>
                    <div className="space-y-2 max-h-[300px] overflow-y-auto p-2 bg-muted/10 rounded-xl">
                      {logs.length > 0 ? (
                        logs.map((log, index) => (
                          <div 
                            key={index} 
                            className="flex items-start gap-2 text-sm text-muted-foreground slide-in-from-bottom-2 p-2 border-b border-muted/20 last:border-0"
                            style={{ animationDelay: `${index * 150}ms` }}
                          >
                            {index === logs.length - 1 && isLoading ? (
                              <img 
                                src="cg.png" 
                                alt="CG Logo" 
                                className="h-4 w-4 animate-spin mt-1"
                                style={{ animationDuration: '0.5s' }}
                              />
                            ) : (
                              <div className="flex items-center mt-1">
                                <span>→</span>
                              </div>
                            )}
                            <div className="flex-1">{log}</div>
                          </div>
                        ))
                      ) : (
                        <div className="text-center text-muted-foreground py-4">
                          {isLoading ? "Waiting for logs..." : "No logs available."}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

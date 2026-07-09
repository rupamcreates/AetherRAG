"use client";

import { useState, useEffect, useRef } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import {
  MessageSquare,
  Plus,
  Trash2,
  Send,
  Layers,
  Menu,
  X,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileCode,
  BookOpen,
  ArrowLeft,
  RefreshCw
} from "lucide-react";
import DocumentUploader from "@/components/DocumentUploader";

interface Thread {
  id: string;
  title: string;
  created_at: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface DocumentInfo {
  id: string;
  name: string;
  file_type: string;
  status: string;
  error_message: string | null;
  created_at: string;
}

interface Citation {
  source: string;
  page_number: number;
  content_preview: string;
}

export default function ChatDashboard() {
  const { getToken } = useAuth();
  
  // App States
  const [threads, setThreads] = useState<Thread[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);
  
  // Interaction States
  const [inputMessage, setInputMessage] = useState("");
  const [newThreadTitle, setNewThreadTitle] = useState("");
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  
  // Loading indicators
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [loadingDocs, setLoadingDocs] = useState(true);
  
  const chatEndRef = useRef<HTMLDivElement>(null);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

  // Fetch initial data on mount
  useEffect(() => {
    fetchThreads();
    fetchDocuments();
  }, []);

  // Poll document ingestion status if there are pending/processing docs
  useEffect(() => {
    const hasUnfinishedDocs = documents.some(
      (doc) => doc.status === "pending" || doc.status === "processing"
    );

    if (hasUnfinishedDocs) {
      const interval = setInterval(() => {
        fetchDocuments();
      }, 5000); // Poll every 5s
      return () => clearInterval(interval);
    }
  }, [documents]);

  // Scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load message history when thread selection changes
  useEffect(() => {
    if (currentThreadId) {
      fetchHistory(currentThreadId);
    } else {
      setMessages([]);
      setCitations([]);
    }
    setActiveCitation(null);
  }, [currentThreadId]);

  // Fetch functions
  const fetchThreads = async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/chat/threads`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setThreads(data);
        if (data.length > 0 && !currentThreadId) {
          setCurrentThreadId(data[0].id);
        }
      }
    } catch (err) {
      console.error("Error fetching threads:", err);
    } finally {
      setLoadingThreads(false);
    }
  };

  const fetchDocuments = async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/documents/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setDocuments(data);
      }
    } catch (err) {
      console.error("Error fetching documents:", err);
    } finally {
      setLoadingDocs(false);
    }
  };

  const fetchHistory = async (threadId: string) => {
    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/chat/threads/${threadId}/history`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data);
      }
    } catch (err) {
      console.error("Error fetching message history:", err);
    }
  };

  // Actions
  const handleCreateThread = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = newThreadTitle.trim() || "New Chat";
    
    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/chat/threads`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ title }),
      });
      
      if (res.ok) {
        const data = await res.json();
        setThreads([data, ...threads]);
        setCurrentThreadId(data.id);
        setNewThreadTitle("");
      }
    } catch (err) {
      console.error("Error creating thread:", err);
    }
  };

  const handleDeleteThread = async (threadId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this chat thread?")) return;

    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/chat/threads/${threadId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      
      if (res.ok) {
        const remaining = threads.filter((t) => t.id !== threadId);
        setThreads(remaining);
        if (currentThreadId === threadId) {
          setCurrentThreadId(remaining.length > 0 ? remaining[0].id : null);
        }
      }
    } catch (err) {
      console.error("Error deleting thread:", err);
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!confirm("Are you sure you want to delete this document? All chunks will be removed.")) return;
    
    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/documents/${docId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setDocuments(documents.filter((d) => d.id !== docId));
      }
    } catch (err) {
      console.error("Error deleting document:", err);
    }
  };

  const handleQuerySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || !currentThreadId || loadingQuery) return;

    const queryText = inputMessage;
    setInputMessage("");
    setLoadingQuery(true);
    setActiveCitation(null);

    // Append user message immediately
    const updatedMessages = [...messages, { role: "user" as const, content: queryText }];
    setMessages(updatedMessages);

    try {
      const token = await getToken();
      const res = await fetch(`${apiUrl}/chat/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          thread_id: currentThreadId,
          message: queryText,
        }),
      });

      if (!res.ok) {
        throw new Error("Failed to execute query");
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder("utf-8");
      if (!reader) throw new Error("No reader available");

      let assistantAnswer = "";
      let isStreaming = true;

      // Add a blank placeholder assistant message that we will append to
      setMessages([...updatedMessages, { role: "assistant" as const, content: "" }]);

      while (isStreaming) {
        const { value, done } = await reader.read();
        if (done) {
          isStreaming = false;
          break;
        }

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data: ")) continue;
          
          try {
            const parsed = JSON.parse(trimmed.slice(6));
            if (parsed.token !== undefined) {
              assistantAnswer += parsed.token;
              setMessages([
                ...updatedMessages,
                { role: "assistant" as const, content: assistantAnswer }
              ]);
            } else if (parsed.citations !== undefined) {
              if (parsed.citations.length > 0) {
                setCitations((prev) => {
                  const merged = [...prev];
                  parsed.citations.forEach((newCite: Citation) => {
                    const exists = merged.some(
                      (c) => c.source === newCite.source && c.page_number === newCite.page_number
                    );
                    if (!exists) merged.push(newCite);
                  });
                  return merged;
                });
              }
            }
          } catch (e) {
            // Ignore partial/malformed JSON during chunk boundaries
          }
        }
      }
      
    } catch (err: any) {
      console.error(err);
      setMessages([
        ...updatedMessages,
        {
          role: "assistant",
          content: "Sorry, an error occurred while processing your request.",
        },
      ]);
    } finally {
      setLoadingQuery(false);
    }
  };

  // Find citation information by key
  const handleCitationClick = (source: string, pageNumber: number) => {
    const citation = citations.find(
      (c) => c.source === source && c.page_number === pageNumber
    );
    if (citation) {
      setActiveCitation(citation);
    } else {
      // Fallback in case citation object wasn't returned in the latest payload (e.g. from history load)
      setActiveCitation({
        source,
        page_number: pageNumber,
        content_preview: "Source context loading failed or wasn't saved in current session metadata."
      });
    }
  };

  // Parse assistant response to render clickable citations
  const renderMessageContent = (content: string) => {
    const regex = /\[([^\]]+_Page\d+)\]/g;
    const parts = content.split(regex);
    if (parts.length === 1) return content;

    return parts.map((part, i) => {
      if (i % 2 === 1) {
        const citeKey = part; // e.g., "report.pdf_Page4"
        const underscoreIdx = citeKey.lastIndexOf("_Page");
        const source = citeKey.substring(0, underscoreIdx);
        const pageNumber = parseInt(citeKey.substring(underscoreIdx + 5), 10);

        return (
          <button
            key={i}
            onClick={() => handleCitationClick(source, pageNumber)}
            className="inline-flex items-center mx-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/40 hover:text-white transition-all cursor-pointer align-baseline"
          >
            {source} (p. {pageNumber})
          </button>
        );
      }
      return part;
    });
  };

  return (
    <div className="flex h-screen w-screen bg-zinc-950 text-zinc-100 font-sans overflow-hidden">
      {/* Mobile Sidebar Hamburger Toggle */}
      <div className="absolute top-4 left-4 z-40 lg:hidden">
        <button
          onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
          className="flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-200 cursor-pointer"
        >
          {mobileSidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {/* Sidebar Panel */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-80 flex-col border-r border-zinc-800 bg-zinc-900/90 backdrop-blur-md transition-transform duration-300 lg:static lg:translate-x-0 ${
          mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Sidebar Header */}
        <div className="flex h-16 items-center justify-between border-b border-zinc-800 px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-600 to-cyan-500">
              <Layers className="h-4 w-4 text-white" />
            </div>
            <span className="font-bold text-zinc-100 text-lg">AetherRAG</span>
          </div>
          <UserButton />
        </div>

        {/* Sidebar Scrollable Section */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Thread Creation Form */}
          <div>
            <form onSubmit={handleCreateThread} className="flex gap-2">
              <input
                type="text"
                placeholder="New thread title..."
                value={newThreadTitle}
                onChange={(e) => setNewThreadTitle(e.target.value)}
                className="flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
              <button
                type="submit"
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-800 text-zinc-200 hover:bg-zinc-700 transition-colors cursor-pointer"
              >
                <Plus className="h-4 w-4" />
              </button>
            </form>
          </div>

          {/* Threads List */}
          <div>
            <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-1">
              Conversations
            </h3>
            {loadingThreads ? (
              <div className="flex items-center gap-2 text-xs text-zinc-500 p-2">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading chats...
              </div>
            ) : threads.length === 0 ? (
              <div className="text-xs text-zinc-600 p-2">No active chats.</div>
            ) : (
              <div className="space-y-1">
                {threads.map((t) => (
                  <div
                    key={t.id}
                    onClick={() => {
                      setCurrentThreadId(t.id);
                      setMobileSidebarOpen(false);
                    }}
                    className={`group flex items-center justify-between rounded-lg px-3 py-2 text-xs font-medium cursor-pointer transition-colors ${
                      currentThreadId === t.id
                        ? "bg-indigo-600/10 text-indigo-400 border border-indigo-600/20"
                        : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 border border-transparent"
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{t.title}</span>
                    </div>
                    <button
                      onClick={(e) => handleDeleteThread(t.id, e)}
                      className="opacity-0 group-hover:opacity-100 hover:text-rose-400 p-0.5 text-zinc-500 transition-opacity cursor-pointer"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Document Ingestion Widget */}
          <DocumentUploader onUploadSuccess={fetchDocuments} />

          {/* Ingested Documents List */}
          <div>
            <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 px-1">
              Source Knowledge
            </h3>
            {loadingDocs ? (
              <div className="flex items-center gap-2 text-xs text-zinc-500 p-2">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading documents...
              </div>
            ) : documents.length === 0 ? (
              <div className="text-xs text-zinc-600 p-2">No documents uploaded.</div>
            ) : (
              <div className="space-y-1.5">
                {documents.map((d) => (
                  <div
                    key={d.id}
                    className="flex flex-col gap-1 rounded-lg bg-zinc-950 border border-zinc-800/80 p-2.5"
                  >
                    <div className="flex items-start justify-between gap-1.5">
                      <div className="flex items-start gap-1.5 truncate">
                        <FileText className="h-3.5 w-3.5 text-zinc-400 shrink-0 mt-0.5" />
                        <span className="text-[11px] font-semibold text-zinc-300 truncate" title={d.name}>
                          {d.name}
                        </span>
                      </div>
                      <button
                        onClick={() => handleDeleteDocument(d.id)}
                        className="text-zinc-600 hover:text-rose-400 transition-colors p-0.5 cursor-pointer"
                        title="Delete Document"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>

                    <div className="flex items-center justify-between mt-1 text-[9px]">
                      {d.status === "completed" && (
                        <span className="flex items-center gap-1 text-emerald-400 font-medium">
                          <CheckCircle2 className="h-3 w-3 shrink-0" />
                          Ready
                        </span>
                      )}
                      {d.status === "pending" && (
                        <span className="flex items-center gap-1 text-amber-500 font-medium">
                          <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                          Queued
                        </span>
                      )}
                      {d.status === "processing" && (
                        <span className="flex items-center gap-1 text-indigo-400 font-medium">
                          <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                          Indexing
                        </span>
                      )}
                      {d.status === "failed" && (
                        <span className="flex items-center gap-1 text-rose-500 font-medium" title={d.error_message || ""}>
                          <AlertCircle className="h-3 w-3 shrink-0" />
                          Failed
                        </span>
                      )}
                      <span className="text-zinc-600">
                        {new Date(d.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main Conversation Window */}
      <section className="flex-1 flex flex-col min-w-0 bg-zinc-950">
        {/* Chat Header */}
        <div className="flex h-16 items-center border-b border-zinc-800/80 px-6 shrink-0 lg:pl-6 pl-16">
          <div className="flex flex-col">
            <span className="text-xs text-zinc-500 font-semibold uppercase tracking-widest">Active Chat</span>
            <span className="text-sm font-bold text-zinc-200 truncate max-w-md">
              {threads.find((t) => t.id === currentThreadId)?.title || "Select or start a chat thread"}
            </span>
          </div>
        </div>

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {currentThreadId ? (
            messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center text-zinc-500">
                <MessageSquare className="h-10 w-10 text-zinc-800 mb-2" />
                <p className="text-sm font-medium">No messages in this chat thread.</p>
                <p className="text-xs text-zinc-600 mt-1 max-w-xs">
                  Ask a question to query your uploaded PDF, CSV, Excel, Word, or Image assets.
                </p>
              </div>
            ) : (
              <div className="space-y-6 max-w-4xl mx-auto">
                {messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`flex gap-3 max-w-[85%] ${
                      msg.role === "user" ? "ml-auto flex-row-reverse" : "mr-auto"
                    }`}
                  >
                    <div
                      className={`flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-lg text-xs font-semibold ${
                        msg.role === "user"
                          ? "bg-zinc-800 text-zinc-200 border border-zinc-700"
                          : "bg-gradient-to-tr from-indigo-600 to-cyan-500 text-white"
                      }`}
                    >
                      {msg.role === "user" ? "U" : "AI"}
                    </div>

                    <div
                      className={`rounded-2xl px-4 py-3 text-sm leading-relaxed border ${
                        msg.role === "user"
                          ? "bg-zinc-900 border-zinc-800 text-zinc-100"
                          : "bg-zinc-950 border-zinc-800/80 text-zinc-300"
                      }`}
                    >
                      <div className="whitespace-pre-line">
                        {msg.role === "assistant"
                          ? renderMessageContent(msg.content)
                          : msg.content}
                      </div>
                    </div>
                  </div>
                ))}
                
                {loadingQuery && (
                  <div className="flex gap-3 mr-auto max-w-[80%]">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-600 to-cyan-500 text-white">
                      <Loader2 className="h-4 w-4 animate-spin" />
                    </div>
                    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-950 px-4 py-3 text-sm text-zinc-500 flex items-center gap-2">
                      <RefreshCw className="h-4 w-4 animate-spin text-indigo-400" />
                      Analyzing knowledge graphs & formulating response...
                    </div>
                  </div>
                )}
                
                <div ref={chatEndRef} />
              </div>
            )
          ) : (
            <div className="flex h-full flex-col items-center justify-center text-center text-zinc-500">
              <Layers className="h-12 w-12 text-zinc-800 mb-3" />
              <p className="text-sm font-semibold">Welcome to AetherRAG</p>
              <p className="text-xs text-zinc-600 mt-1 max-w-sm">
                Create a chat thread on the sidebar, upload your documents, and start querying layout-aware multimodal knowledge bases.
              </p>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <div className="border-t border-zinc-800/80 p-4 shrink-0 bg-zinc-950">
          <form onSubmit={handleQuerySubmit} className="max-w-4xl mx-auto flex gap-2">
            <input
              type="text"
              placeholder={
                currentThreadId
                  ? "Query documents (e.g., 'What was the Q3 revenue in the table on page 4?')..."
                  : "Please select or create a chat thread first"
              }
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              disabled={!currentThreadId || loadingQuery}
              className="flex-1 rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!currentThreadId || !inputMessage.trim() || loadingQuery}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-40 disabled:hover:bg-indigo-600 cursor-pointer"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </section>

      {/* Interactive Citation Drawer Overlay */}
      {activeCitation && (
        <div className="fixed inset-y-0 right-0 z-50 flex w-96 flex-col border-l border-zinc-800 bg-zinc-900/95 backdrop-blur-md shadow-2xl p-6 transition-all duration-300">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-4 mb-4">
            <div className="flex items-center gap-2 text-indigo-400">
              <BookOpen className="h-5 w-5" />
              <span className="font-bold text-sm">Source Citation Details</span>
            </div>
            <button
              onClick={() => setActiveCitation(null)}
              className="rounded-lg p-1 text-zinc-500 hover:text-zinc-200 cursor-pointer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-4 overflow-y-auto flex-1">
            <div className="rounded-lg bg-zinc-950 p-3 border border-zinc-800">
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold">Document Name</div>
              <div className="text-xs font-bold text-zinc-200 break-all">{activeCitation.source}</div>
            </div>

            <div className="rounded-lg bg-zinc-950 p-3 border border-zinc-800">
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold">Page Reference</div>
              <div className="text-xs font-bold text-zinc-200">Page {activeCitation.page_number}</div>
            </div>

            <div className="rounded-lg bg-zinc-950/40 p-4 border border-zinc-800 flex-1">
              <div className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold mb-2">Chunk Snippet (Context Used)</div>
              <p className="text-xs text-zinc-300 leading-relaxed italic whitespace-pre-wrap bg-zinc-950/80 p-3 rounded-lg border border-zinc-800/50">
                "{activeCitation.content_preview}"
              </p>
            </div>
          </div>
          
          <div className="border-t border-zinc-800 pt-4 mt-4">
            <button
              onClick={() => setActiveCitation(null)}
              className="w-full flex items-center justify-center gap-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 py-2 text-xs font-semibold transition-colors cursor-pointer text-zinc-200"
            >
              <ArrowLeft className="h-4 w-4" />
              Close Preview
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

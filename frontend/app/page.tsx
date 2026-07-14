import Link from "next/link";
import { auth } from "@clerk/nextjs/server";
import { ArrowRight, FileText, Database, Shield, Cpu, RefreshCw, Layers } from "lucide-react";

export default async function Home() {
  const { userId } = await auth();

  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100 font-sans selection:bg-indigo-500 selection:text-white overflow-x-hidden relative">
      {/* Background Decorative Gradients */}
      <div className="absolute inset-0 -z-10 h-full w-full bg-[linear-gradient(to_right,#1f1f23_1px,transparent_1px),linear-gradient(to_bottom,#1f1f23_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-35" />
      <div className="absolute top-0 right-1/4 -z-10 h-[400px] w-[600px] rounded-full bg-indigo-600/10 blur-[120px] pointer-events-none" />
      <div className="absolute top-1/3 left-1/4 -z-10 h-[500px] w-[500px] rounded-full bg-cyan-600/10 blur-[130px] pointer-events-none" />

      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b border-zinc-800/50 bg-zinc-950/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 to-cyan-500 shadow-lg shadow-indigo-500/20">
              <Layers className="h-5 w-5 text-white" />
            </div>
            <span className="text-xl font-bold bg-gradient-to-r from-white via-zinc-200 to-zinc-400 bg-clip-text text-transparent">
              AetherRAG
            </span>
          </div>

          <nav className="flex items-center gap-4">
            {userId ? (
              <Link
                href="/chat"
                className="flex items-center gap-1.5 rounded-xl bg-zinc-800 px-4 py-2 text-sm font-semibold hover:bg-zinc-700 transition-all border border-zinc-700/50"
              >
                Go to Dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
            ) : (
              <>
                <Link
                  href="/sign-in"
                  className="text-sm font-medium hover:text-white transition-colors"
                >
                  Sign In
                </Link>
                <Link
                  href="/sign-up"
                  className="flex items-center gap-1 rounded-xl bg-gradient-to-r from-indigo-600 to-cyan-600 px-4 py-2 text-sm font-semibold hover:opacity-95 shadow-lg shadow-indigo-600/25 transition-all text-white"
                >
                  Get Started
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1">
        <section className="mx-auto max-w-7xl px-6 pt-24 pb-20 text-center md:pt-32">
          <div className="mx-auto max-w-4xl">
            {/* Tagline Badge */}
            <div className="inline-flex items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/5 px-3 py-1 text-xs font-semibold text-indigo-400 mb-6">
              <Cpu className="h-3.5 w-3.5" />
              Layout-Aware Multimodal RAG
            </div>
            
            <h1 className="text-4xl font-extrabold tracking-tight sm:text-6xl bg-gradient-to-b from-white via-zinc-100 to-zinc-400 bg-clip-text text-transparent leading-none">
              Production-Ready Document RAG <br />
              <span className="bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">
                With Deep Reasoning & Citations
              </span>
            </h1>
            
            <p className="mx-auto mt-6 max-w-2xl text-lg text-zinc-400 leading-relaxed">
              Upload complex PDFs, DOCX, CSVs, and Excel sheets. Extract tables and images layout-awarely, semantic-chunk them, and query them with multi-query reciprocal rank fusion.
            </p>

            <div className="mt-10 flex justify-center gap-4">
              <Link
                href={userId ? "/chat" : "/sign-up"}
                className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-indigo-600 to-cyan-600 px-8 py-4 text-base font-semibold shadow-xl shadow-indigo-600/30 hover:shadow-indigo-600/40 transition-all hover:scale-[1.01] text-white"
              >
                Start Querying Free
                <ArrowRight className="h-5 w-5" />
              </Link>
            </div>
          </div>

          {/* Feature Grid */}
          <div className="mx-auto mt-32 max-w-6xl grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-3">
            {/* Feature 1 */}
            <div className="flex flex-col items-start rounded-2xl border border-zinc-800/80 bg-zinc-900/50 p-8 backdrop-blur-sm transition-all hover:border-zinc-700/50">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-400 mb-5">
                <FileText className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-white mb-2">Multimodal Parsing</h3>
              <p className="text-zinc-400 text-sm leading-relaxed text-left">
                Uses layout-aware parsing (`unstructured.io`) to process complex PDFs with tables, charts, DOCX, CSVs, and Excel sheets. Retains full structure.
              </p>
            </div>

            {/* Feature 2 */}
            <div className="flex flex-col items-start rounded-2xl border border-zinc-800/80 bg-zinc-900/50 p-8 backdrop-blur-sm transition-all hover:border-zinc-700/50">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-400 mb-5">
                <Database className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-white mb-2">Advanced Retrieval</h3>
              <p className="text-zinc-400 text-sm leading-relaxed text-left">
                Combines semantic vector search (`pgvector`) and Full Text Search, expands user queries with multi-query routing, and merges them using Reciprocal Rank Fusion (RRF).
              </p>
            </div>

            {/* Feature 3 */}
            <div className="flex flex-col items-start rounded-2xl border border-zinc-800/80 bg-zinc-900/50 p-8 backdrop-blur-sm transition-all hover:border-zinc-700/50">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-teal-500/10 text-teal-400 mb-5">
                <Shield className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-white mb-2">Inline Citations</h3>
              <p className="text-zinc-400 text-sm leading-relaxed text-left">
                Response generation using Groq LLM requires strict inline citations. Hover over references to view document page previews and verify sources instantly.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-900 bg-zinc-950 py-8">
        <div className="mx-auto max-w-7xl px-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-zinc-500 text-sm">
            <Layers className="h-4 w-4" />
            <span>© 2026 AetherRAG. All rights reserved.</span>
          </div>
          <div className="flex gap-6 text-sm text-zinc-500">
            <span className="hover:text-zinc-400 cursor-pointer">Privacy</span>
            <span className="hover:text-zinc-400 cursor-pointer">Terms</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

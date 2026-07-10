import logging
from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker

logger = logging.getLogger(__name__)

class DocumentChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200, use_semantic: bool = False):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.use_semantic = use_semantic
        self.embeddings = None

        # Initialize splitters
        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        
        self.semantic_splitter = None
        if self.use_semantic:
            try:
                # Use local fastembed embeddings for offline-capable semantic chunking
                from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
                self.embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")
                self.semantic_splitter = SemanticChunker(
                    self.embeddings,
                    breakpoint_threshold_type="percentile"
                )
                logger.info("Initialized local FastEmbedEmbeddings for semantic chunking.")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize local FastEmbedEmbeddings ({e}). "
                    "Semantic chunking will fall back to recursive character splitting."
                )

    def chunk_document(self, parsed_elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Chunks parsed elements. Tables are kept intact. Text elements are grouped by page
        and chunked recursively or semantically.
        """
        chunks = []
        
        # Group elements by page and separate tables
        pages_text: Dict[int, List[str]] = {}
        page_metadata_template: Dict[int, Dict[str, Any]] = {}
        
        for element in parsed_elements:
            el_type = element.get("type", "NarrativeText")
            text = element.get("text", "")
            metadata = element.get("metadata", {})
            page_num = metadata.get("page_number", 1)
            
            if el_type == "Table":
                # Tables are kept intact as individual chunks
                chunks.append({
                    "content": text,
                    "metadata": {
                        **metadata,
                        "type": "table"
                    }
                })
            else:
                # Narrative/Text block
                if page_num not in pages_text:
                    pages_text[page_num] = []
                    # Create a template of metadata for this page
                    page_metadata_template[page_num] = {
                        "source": metadata.get("source", "unknown"),
                        "file_type": metadata.get("file_type", "unknown"),
                        "page_number": page_num
                    }
                    if "section" in metadata:
                        page_metadata_template[page_num]["section"] = metadata["section"]
                
                pages_text[page_num].append(text)
                
        # Chunk text pages
        for page_num, text_blocks in pages_text.items():
            if not text_blocks:
                continue
            
            full_page_text = "\n".join(text_blocks)
            metadata = page_metadata_template[page_num]
            metadata["type"] = "text"
            
            if self.use_semantic and self.semantic_splitter:
                try:
                    logger.info(f"Applying semantic chunking to page {page_num}...")
                    docs = self.semantic_splitter.create_documents([full_page_text])
                    for doc in docs:
                        chunks.append({
                            "content": doc.page_content,
                            "metadata": metadata.copy()
                        })
                except Exception as e:
                    logger.error(f"Semantic chunking failed for page {page_num}, falling back to recursive: {e}")
                    docs = self.recursive_splitter.create_documents([full_page_text])
                    for doc in docs:
                        chunks.append({
                            "content": doc.page_content,
                            "metadata": metadata.copy()
                        })
            else:
                logger.info(f"Applying recursive chunking to page {page_num}...")
                docs = self.recursive_splitter.create_documents([full_page_text])
                for doc in docs:
                    chunks.append({
                        "content": doc.page_content,
                        "metadata": metadata.copy()
                    })
                    
        logger.info(f"Created {len(chunks)} chunks from parsed document.")
        return chunks

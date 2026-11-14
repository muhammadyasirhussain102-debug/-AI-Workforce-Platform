import re
from typing import List, Dict, Any, Optional
from uuid import UUID

class PolicyChunker:
    """Document text ko structured chunks mein divide karta hai without breaking clauses."""
    
    @staticmethod
    def clean_text(raw_text: str) -> str:
        # Extra spaces aur weird unicode characters ko clean karta hai
        cleaned = re.sub(r'\s+', ' ', raw_text).strip()
        return cleaned

    @classmethod
    def chunk_by_section(
        cls, 
        document_text: str, 
        section_title: str = "General", 
        chunk_size: int = 500
    ) -> List[Dict[str, Any]]:
        cleaned = cls.clean_text(document_text)
        words = cleaned.split()
        chunks = []
        
        # Simple sliding window approach with small overlap
        step = chunk_size - 50 if chunk_size > 50 else chunk_size
        for i in range(0, len(words), step):
            chunk_words = words[i:i + chunk_size]
            chunk_text = " ".join(chunk_words)
            if chunk_text:
                chunks.append({
                    "section_path": section_title,
                    "text": chunk_text,
                    "word_count": len(chunk_words)
                })
        return chunks


class PolicySearchEngine:
    """
    Roadmap Rule 4: SQL filter pehle lagta hai taake hr_only data employee tak na pohnche.
    """
    
    @classmethod
    def build_secure_query(cls, tenant_id: str, user_role: str, search_term: str):
        # Employee sirf general docs dekh sakta hai, HR dono dekh sakta hai
        if user_role in ["hr_admin", "admin"]:
            allowed_visibilities = ["all", "hr_only"]
        else:
            allowed_visibilities = ["all"]

        return {
            "tenant_id": tenant_id,
            "user_role": user_role,
            "search_term": search_term,
            "allowed_visibilities": allowed_visibilities,
        }
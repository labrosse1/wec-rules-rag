## ADR-000: Project definition
```
Status: Accepted
Date: 2026-09-29
Scope: Defining the project scope and components used.
```

### Context

I am building a RAG system over the FIA WEC regulations 2026 using LlamaIndex.  
The final objective is to have a functional RAG over the official pdf document deployed as a Hugging Face space with a Gradio UI.
The stack used will be open-source for the processing steps (extraction, splitting, storage) even though the models will be reached through APIs since I don't have enough power to host open-weight models locally. (No GPU with sufficient VRAM)  

### Technical stack

- PyMuPDF -> Text extraction. This will run locally (Python library)  
- LlamaIndex -> Text splitting and metadata before embedding conversion. Simplifies the whole pipeline creation (Python framework)
- Voyage-4-lite -> Embeddings model with 32k context window. 
- ChromaDB -> Open-source DB for vectors and supporting metadata search.
- Gemini 3.5 Flash-Lite -> Final answer generation. (No option to run a model smart/fast enough on my local pc)

### Technical decisions

**Extraction**
PyMuPDF will be used for this project since it's very fast and light. The document does not contain tables which require very precise extraction like in pdfplumber.

**Embeddings model**  
As the WEC 2026 regulation is a public document, it doesn't really matter if the text of the document is going through an API.    
I decided to use Voyage-4-lite [Model info](https://blog.voyageai.com/2026/01/15/voyage-4/). This model costs $0.02/m tokens with the first 200M tokens free which will allow me to create the embeddings for the full documents for free.(1024 dimension by default and 32k context window).
Alternatives considered: voyage-4-nano is open-weight and would fit the open-source goal, but my PC doesn’t have the resources to serve it. Since the Voyage 4 models share the same embedding space, switching to nano later (e.g. on dedicated hardware) would not require re-indexing the document.

**Database**
I chose to use ChromaDB for this project since Chroma is easy to start, light, and well integrated with LlamaIndex. At the moment, I only plan to store the embeddings from one single document. Therefore, using Qdrant or FAISS would be overkill.

**Model**
Gemini 3.5 Flash-Lite will be the model used for the final answer generation because it's low latency and cheap.  
0.3 dollars input /M 
2.5 dollars output /M
(Updated on 2026-10-28)


# Governance corpus

The RAG layer (`rag/`) indexes the documents in this directory so the agents
can cite policy with stable `doc:section` ids. **Place the corpus here
yourself** — these files are not fetched and (for the real regulatory PDFs)
not committed.

Expected files (Markdown preferred — convert PDFs to `.md` so section numbers
and chunk boundaries stay under our control):

| File | `doc_id` | Role |
|------|----------|------|
| `sr_26_2.md` | `SR_26-2` | Primary, current guidance (2026) |
| `sr_11_7.md` | `SR_11-7` | Historical predecessor (superseded) |
| `eu_ai_act.md` | `EU_AI_Act` | High-risk obligations excerpt |
| `nist_ai_rmf.md` | `NIST_AI_RMF` | Risk-management framework |
| `model_validation_synthetic.md` | `ModelVal` | Synthetic validation report (clearly labeled) |

## Chunking & citations

Each Markdown heading and the text beneath it (until the next heading) becomes
one citable chunk. The section id is the leading section label in the heading
when present (`## III.B Threshold setting` → `III.B`), otherwise a slug of the
heading text. A drafted memo therefore cites e.g. `SR_26-2:III.B`, and that
string resolves to the same passage on every re-index.

## Note on real vs. synthetic

For local development and the test suite, small **synthetic** stand-ins live in
`rag/tests/fixtures/governance/` (clearly labeled). They let the pipeline run
end-to-end without the real documents. Drop the real corpus here and point the
agents at it with `GOVERNANCE_CORPUS_DIR` (defaults to this directory).

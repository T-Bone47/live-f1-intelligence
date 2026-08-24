# AI_GROUNDING.md

Two validators guard every answer.

PackValidator (pre-flight, rejects malformed context):
pack name in known set; session_id present; facts non-empty; unique string ids;
class in A-F; statement present. No silent repair - rejection surfaces as a
deterministic fallback.

ResponseValidator (post-generation):
1. every cited evidence id must exist in the pack;
2. every float in the answer must match a number from cited facts (or be a
   simple difference of two such numbers, tol 0.05);
3. integers >99 must appear among cited numbers;
4. every #N driver token must appear in cited statements or numeric universes.

Retry contract: ONE regeneration attempt with an explicit correction suffix
naming the failure. Persistent failure -> deterministic_fallback answer built
from the same pack facts (model=deterministic-fallback). The dashboard always
has something truthful to show.

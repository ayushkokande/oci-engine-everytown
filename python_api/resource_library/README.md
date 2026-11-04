# Resource_Library

Every `*.md` file in this folder (except this README) is injected, in full, into the
recommendation prompt as a labeled `<resource>` block. The model may cite entries only
by their `id`.

**Only non-confidential material belongs here.** This repo is open source. Everytown's
reference materials stay in the git-ignored `Everytown/Everytown_OCI_Package/04_Reference_Materials/`
or `private/` folders until they are cleared for distribution (see Open Assumption 2 in the spec).

The `R*` entries shipped with the MVP are **starter entries written for the hackathon**. They
contain general, widely used nonprofit capacity-building practice, not Everytown guidance. Replace
or extend them with cleared CVI resources.

Front matter fields:

```
---
id: R1                 # stable id the model cites
title: Short title
domains: PL, FR        # OCI domain ids this resource supports
source: Where it came from / licence
---
```

If the library grows beyond what fits in the prompt, switch to the Bedrock Knowledge Base
stretch goal (task 13.2); the orchestrator's two-call shape stays the same.

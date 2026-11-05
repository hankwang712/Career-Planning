# JobHunter integration

Source: https://github.com/Bynlk/JobHunter

Pinned commit: `4b5a69010a98b3d80b408fd983c1c2dfa60788e4`.

License: MIT; the full upstream notice is retained in `vendor/LICENSE`.

Public website collection checks visible verification/login walls; a normal login navigation link or a captcha script in HTML does not classify the whole public page as blocked.

The crawler package, configuration and company-directory JSON are vendored from this commit. The standalone Flask app, Vue UI and database layer are not run: the host application supplies authenticated APIs, durable collection runs, a scheduler, provenance, market observations, filtering and export.

Local changes to vendor files: browser executable override, runtime log directory override, bounded/offset/nested API pagination, forwarding source-specific headers, preservation of NCSS salary decimals, conservative job-type inference, and incremental detail enrichment callbacks. Tencent's detail URL and list mapping are corrected against its current official frontend; the bridge fetches real responsibilities/requirements instead of treating its recruiting-project label as a JD. The JSONL bridge adds stable source IDs, record/time limits and reports unavailable/partial sources without inventing successful collections.

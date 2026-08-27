"""Phase 6: corpus source registry (families × documents).

Every entry is {family, id, url, filename}. Remote entries are fetched by
expand.py; "generate:" URLs mark locally synthesised documents (logs, code
docs) so the corpus stays reproducible without network luck.

Coverage goal (mission §11): >=20 families, >=10 docs/family eventually --
this registry is the growth surface; add rows, rerun expand.py + perturb.py.
Existing ids (co2_data, k8s_deployment, sec_filing, operating_review,
sales_report) are owned by fetch.py/add_local_samples and must keep their ids.
"""

FAMILIES: dict[str, list[dict]] = {
    # ---------------------------------------------------------- csv_datasets
    "csv_datasets": [
        {"id": "co2_data", "url": "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv", "filename": "co2.csv"},
    ],
    # ------------------------------------------------------------ k8s_docs
    "kubernetes_docs": [
        {"id": "k8s_deployment", "url": "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/controllers/deployment.md", "filename": "deployment.md"},
        {"id": "k8s_services", "url": "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/services-networking/service.md", "filename": "service.md"},
        {"id": "k8s_configmap", "url": "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/configuration/configmap.md", "filename": "configmap.md"},
    ],
    # ------------------------------------------------------- rfc_technical
    "rfc_technical": [
        {"id": "rfc2616_http", "url": "https://www.rfc-editor.org/rfc/rfc2616.txt", "filename": "rfc2616.txt"},
        {"id": "rfc1035_dns", "url": "https://www.rfc-editor.org/rfc/rfc1035.txt", "filename": "rfc1035.txt"},
    ],
    # -------------------------------------------------------- prose_books
    "prose_books": [
        {"id": "alice_prose", "url": "https://www.gutenberg.org/files/11/11-0.txt", "filename": "alice.txt"},
        {"id": "frankenstein_prose", "url": "https://www.gutenberg.org/files/84/84-0.txt", "filename": "frankenstein.txt"},
        {"id": "pride_prose", "url": "https://www.gutenberg.org/files/1342/1342-0.txt", "filename": "pride.txt"},
    ],
    # --------------------------------------------------------- md_readmes
    "md_readmes": [
        {"id": "readme_requests", "url": "https://raw.githubusercontent.com/psf/requests/main/README.md", "filename": "readme_requests.md"},
        {"id": "readme_fastapi", "url": "https://raw.githubusercontent.com/fastapi/fastapi/master/README.md", "filename": "readme_fastapi.md"},
    ],
    # ------------------------------------------------------------- legal
    "legal_policy": [
        {"id": "github_terms", "url": "https://raw.githubusercontent.com/github/site-policy/main/Policies/github-terms/github-terms-of-service.md", "filename": "github_terms.md"},
    ],
    # -------------------------------------------------- api_spec (JSON)
    # NOTE: fetched into raw/ and the manifest, but tdf.readers has no .json
    # reader, so perturb.py skips it (see the SKIP log) -- it has no
    # perturbed/*.pkl and is excluded from eval runs until JSON is supported.
    "api_spec": [
        {"id": "petstore_openapi", "url": "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/3.1.0/examples/v3.0/petstore.json", "filename": "petstore.json"},
    ],
}

# Locally synthesised families (no network): registered by expand.py itself.
SYNTHETIC_FAMILIES = ("logs_synthetic", "code_documentation")

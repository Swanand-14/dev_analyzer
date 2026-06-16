

# Responsibilities:
#   1. Connect to a GitHub repo via PyGithub
#   2. Walk the file tree and filter out noise (build artifacts, media, etc.)
#   3. Fetch file contents and classify each file into a feature group
#   4. Pack files into token-budget-aware chunks for Gemini

from collections import defaultdict
from typing import Dict, List, Optional

from github.Repository import Repository
from github import Github

from app.services.github.constants import FEATURE_TO_CAPABILITY
from app.services.github.file_utils import (
    should_include_file,
    is_boilerplate,
    is_high_priority,
    extract_code_metadata,
    calculate_feature_score,
)


class ChunkingAnalyzer:
    """
    Connects to a single GitHub repo and produces analysis-ready chunks.

    Usage:
        analyzer = ChunkingAnalyzer(repo_url, github_client)
        file_tree = analyzer.get_file_tree()
        result    = analyzer.chunk_repo()
    """

    # Token / size budgets per chunk
    MAX_CHUNK_SIZE_PRIORITY: int = 15_000   # chars — high priority files
    MAX_CHUNK_SIZE_REGULAR: int  = 10_000   # chars — regular files
    MAX_FILE_SIZE_PRIORITY: int  =  5_000   # chars — max per file in priority chunk
    MAX_FILE_SIZE_REGULAR: int   =  3_000   # chars — max per file in regular chunk

    def __init__(self, repo_url: str, github_client: Github) -> None:
        if not github_client:
            raise ValueError("GitHub client is required — check GITHUB_TOKEN in .env")

        # Parse owner/repo from full URL or shorthand
        if "github.com" in repo_url:
            parts = repo_url.rstrip("/").split("/")
            self.owner     = parts[-2]
            self.repo_name = parts[-1]
        else:
            self.owner, self.repo_name = repo_url.split("/")

        self.repo: Repository = github_client.get_repo(f"{self.owner}/{self.repo_name}")

        # Detect default branch
        self.branch = "main"
        try:
            self.repo.get_branch("main")
        except Exception:
            self.branch = "master"

        self._file_tree: Optional[List[str]] = None
        
        

    def _detect_branch(self) -> str:
        """
        Reads the default branch directly from the repo metadata.
        No extra API call needed — PyGithub fetches this with the repo object.
        """
        try:
            return self.repo.default_branch
        except Exception as e:
            print(f"   ⚠️  Could not read default_branch: {str(e)[:60]}, falling back to 'main'")
            return "main"
    @property
    def file_tree(self) -> List[str]:
        """
        Returns the filtered file tree.
        Fetched once and cached — subsequent calls return the same list.
        """
        if self._file_tree is None:
            self._file_tree = self._fetch_file_tree()
        return self._file_tree
 
    def _fetch_file_tree(self) -> List[str]:
        try:
            sha  = self.repo.get_branch(self.branch).commit.sha
            tree = self.repo.get_git_tree(sha=sha, recursive=True).tree
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch file tree for branch '{self.branch}' on "
                f"{self.owner}/{self.repo_name}: {str(e)}"
            ) from e
 
        filtered = [
            item.path
            for item in tree
            if item.type == "blob" and should_include_file(item.path)
        ]
 
        print(f"   📂 Total repo files: {len(tree)} → After filter: {len(filtered)}")
        return filtered

    def chunk_repo(self) -> Dict:
        """
        Fetches file contents, classifies each file into a feature group,
        and packs them into token-budget-aware chunks.

        Returns:
            {
                chunks:            { feature_name: [chunk, ...] },
                total_files:       int,
                boilerplate_files: int,
                total_chunks:      int,
                repo_name:         str,
                owner:             str,
            }
        """
        files        = self.file_tree
        files_data   = []
        boilerplate  = []

        for file_path in files:
            try:
                content  = self.repo.get_contents(file_path, ref=self.branch).decoded_content.decode("utf-8")
                metadata = extract_code_metadata(content, file_path)

                if is_boilerplate(file_path):
                    boilerplate.append({
                        "file":     file_path,
                        "lines":    len(content.splitlines()),
                        "metadata": metadata,
                    })
                    continue

                scores  = calculate_feature_score(file_path, content, metadata)
                feature = max(scores.items(), key=lambda x: x[1])[0] if scores else "business_logic"

                files_data.append({
                    "file":             file_path,
                    "content":          content,
                    "lines":            len(content.splitlines()),
                    "feature":          feature,
                    "metadata":         metadata,
                    "is_high_priority": is_high_priority(file_path),
                })

            except Exception as e:
                print(f"   ⚠️  Skipped {file_path}: {str(e)[:60]}")

        print(f"   ✅ Analyzed: {len(files_data)} | Boilerplate: {len(boilerplate)}")

        # Group by feature, then build chunks
        feature_groups: Dict[str, List] = defaultdict(list)
        for fd in files_data:
            feature_groups[fd["feature"]].append(fd)

        all_chunks: Dict[str, List] = {}
        total_chunks = 0

        # Boilerplate gets a single summary chunk — no AI analysis needed
        if boilerplate:
            all_chunks["ui_library"] = [self._build_boilerplate_summary(boilerplate)]
            total_chunks += 1

        for feature, group in feature_groups.items():
            if feature == "ui_library":
                continue
            chunks = self._build_chunks_for_feature(group, feature)
            if chunks:
                all_chunks[feature] = chunks
                total_chunks += len(chunks)

        return {
            "chunks":            all_chunks,
            "total_files":       len(files_data),
            "boilerplate_files": len(boilerplate),
            "total_chunks":      total_chunks,
            "repo_name":         self.repo_name,
            "owner":             self.owner,
        }

    # ──────────────────────────────────────────────────────────────
    # CHUNK BUILDERS  (private)
    # ──────────────────────────────────────────────────────────────

    def _build_boilerplate_summary(self, boilerplate_files: List[Dict]) -> Dict:
        """
        Builds a single descriptive chunk for all boilerplate UI files.
        Lists the libraries detected and total file count — no raw code.
        """
        total_lines = sum(f["lines"] for f in boilerplate_files)

        ui_libs = set()
        for f in boilerplate_files:
            for imp in f["metadata"]["imports"]:
                if any(lib in imp for lib in ["radix", "shadcn", "lucide", "@/components/ui"]):
                    ui_libs.add(imp.split("/")[0])

        file_list = "\n".join(f"  - {f['file']}" for f in boilerplate_files[:20])
        if len(boilerplate_files) > 20:
            file_list += f"\n  ... and {len(boilerplate_files) - 20} more"

        return {
            "name":             "UI Library Components",
            "files":            [f["file"] for f in boilerplate_files],
            "total_lines":      total_lines,
            "estimated_tokens": 500,
            "code": (
                f"# UI Library Components\n"
                f"Total: {len(boilerplate_files)}\n"
                f"Libs: {', '.join(sorted(ui_libs))}\n"
                f"{file_list}"
            ),
            "is_boilerplate": True,
        }

    def _build_chunks_for_feature(self, files: List[Dict], feature: str) -> List[Dict]:
        """
        Splits a feature's files into high-priority and regular groups,
        then builds chunks for each group separately.
        """
        if not files:
            return []

        high    = [f for f in files if f["is_high_priority"]]
        regular = [f for f in files if not f["is_high_priority"]]

        chunks = []
        if high:
            chunks.extend(self._pack_files_into_chunks(high, feature, priority=True))
        if regular:
            chunks.extend(self._pack_files_into_chunks(regular, feature, priority=False))

        return chunks

    def _pack_files_into_chunks(
        self, files: List[Dict], feature: str, priority: bool
    ) -> List[Dict]:
        """
        Packs a list of files into N chunks respecting the token budget.
        Priority files get more chunks and larger per-file limits.
        """
        if not files:
            return []

        sorted_files   = sorted(files, key=lambda x: x["lines"], reverse=True)
        max_chunks     = min(len(files), 5) if priority else min(3, max(1, len(files) // 10))
        files_per_chunk = max(1, len(files) // max_chunks)

        chunks = []
        for i in range(0, len(sorted_files), files_per_chunk):
            batch = sorted_files[i: i + files_per_chunk]
            if batch:
                chunks.append(
                    self._build_single_chunk(batch, feature, len(chunks) + 1, max_chunks, priority)
                )
            if len(chunks) >= max_chunks:
                break

        return chunks

    def _build_single_chunk(
        self,
        files:    List[Dict],
        feature:  str,
        num:      int,
        total:    int,
        priority: bool,
    ) -> Dict:
        """
        Assembles the final chunk dict from a batch of files.
        Truncates individual files and stops adding once the chunk size budget is hit.
        """
        max_chunk_size = self.MAX_CHUNK_SIZE_PRIORITY if priority else self.MAX_CHUNK_SIZE_REGULAR
        max_file_size  = self.MAX_FILE_SIZE_PRIORITY  if priority else self.MAX_FILE_SIZE_REGULAR

        code_parts: List[str] = []
        accumulated = 0

        for f in files:
            content = f["content"]
            if len(content) > max_file_size:
                content = content[:max_file_size] + "\n// ... (truncated)\n"

            block = f"// FILE: {f['file']} ({f['lines']} lines)\n{content}"

            if accumulated + len(block) > max_chunk_size:
                break

            code_parts.append(block)
            accumulated += len(block)

        code_content = "\n\n".join(code_parts)
        if len(files) > len(code_parts):
            code_content += f"\n\n// ... plus {len(files) - len(code_parts)} more files"

        # Build a descriptive name for logging
        priority_label = " [PRIORITY]" if priority else ""
        name = f"{feature.replace('_', ' ').title()}{priority_label}"
        if total > 1:
            name += f" (Part {num}/{total})"

        return {
            "name":             name,
            "files":            [f["file"] for f in files],
            "total_lines":      sum(f["lines"] for f in files),
            "estimated_tokens": len(code_content) // 4,
            "code":             code_content,
            "is_boilerplate":   False,
        }
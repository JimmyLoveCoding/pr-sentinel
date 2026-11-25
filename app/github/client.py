"""GitHub 评论发布客户端（真实 API）。

方法与 ReviewCommentStore.add 完全一致（鸭子类型），管线无需感知底层：
- 行内评论（有 file_path + line）：POST /repos/{repo}/pulls/{n}/reviews，
  comments 数组里带 path / line / side=RIGHT / body；
- 汇总评论（无 file_path）：POST /repos/{repo}/issues/{n}/comments。

需要 GITHUB_TOKEN（对目标仓库有 pull requests 写权限）。
transport 参数仅用于单元测试注入 MockTransport；生产环境保持 None 走真实网络。
"""

from __future__ import annotations

import httpx

from app.config import Settings, get_settings

_API = "https://api.github.com"


class GitHubCommentClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=_API,
            headers={
                "Authorization": f"Bearer {self.settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
            transport=transport,  # 测试注入 MockTransport；生产为 None
        )

    def add(
        self,
        *,
        repo: str,
        pr_number: int,
        file_path: str | None,
        line: int | None,
        severity: str,
        body: str,
    ) -> dict:
        """发布一条评论（行内或汇总），返回带 html_url 的结构。"""
        if file_path is not None and line is not None:
            resp = self._client.post(
                f"/repos/{repo}/pulls/{pr_number}/reviews",
                json={
                    "body": f"pr-sentinel 审查（{severity}）",
                    "event": "COMMENT",
                    "comments": [
                        {
                            "path": file_path,
                            "line": line,
                            "side": "RIGHT",  # 行号取自新文件（新增行）
                            "body": body,
                        }
                    ],
                },
            )
            if resp.status_code == 422:
                # 行号不在 diff 范围内等情况：降级为汇总评论，评论不丢失
                resp = self._client.post(
                    f"/repos/{repo}/issues/{pr_number}/comments",
                    json={"body": f"**{file_path}:{line}**\n\n{body}"},
                )
        else:
            resp = self._client.post(
                f"/repos/{repo}/issues/{pr_number}/comments",
                json={"body": body},
            )

        if resp.status_code >= 300:
            raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return {
            "id": data.get("id"),
            "repo": repo,
            "pr_number": pr_number,
            "file_path": file_path,
            "line": line,
            "severity": severity,
            "body": body,
            "url": data.get("html_url", ""),
        }

    def publish_review(
        self,
        *,
        repo: str,
        pr_number: int,
        summary_body: str,
        comments: list[dict],
    ) -> dict:
        """一次提交整批审查：汇总 body + 多条行内评论（同一个 review）。

        个别行号不在 diff 内会导致整批 422——此时降级：逐条发表
        （每条走 add() 自带的 422 降级），汇总报告改发 issue comment。
        """
        payload_comments = [
            {
                "path": c["file_path"],
                "line": c["line"],
                "side": "RIGHT",
                "body": c["body"],
            }
            for c in comments
            if c.get("file_path") and c.get("line")
        ]
        resp = self._client.post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            json={
                "body": summary_body,
                "event": "COMMENT",
                "comments": payload_comments,
            },
        )

        if resp.status_code == 422 and payload_comments:
            posted = [
                self.add(
                    repo=repo,
                    pr_number=pr_number,
                    file_path=c.get("file_path"),
                    line=c.get("line"),
                    severity=c.get("severity", "minor"),
                    body=c["body"],
                )
                for c in comments
            ]
            self._client.post(
                f"/repos/{repo}/issues/{pr_number}/comments",
                json={"body": summary_body},
            )
            return {"degraded": True, "comments": posted, "url": ""}

        if resp.status_code >= 300:
            raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return {
            "degraded": False,
            "url": data.get("html_url", ""),
            "comments": payload_comments,
        }

    def close(self) -> None:
        self._client.close()

from app.core.diff import parse_diff

SAMPLE = """diff --git a/uploader.py b/uploader.py
index 111..222 100644
--- a/uploader.py
+++ b/uploader.py
@@ -40,4 +40,6 @@ def upload(file):
     resp = requests.post(url, files=file)
-    return resp.json()["url"]
+    data = resp.json()
+    return data.get("url")
+    log.info("done")


diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1,2 +1,2 @@
-lod
+old
 text
"""


def test_parse_files_and_hunks() -> None:
    files = parse_diff(SAMPLE)
    assert [f.path for f in files] == ["uploader.py", "docs/readme.md"]

    uploader = files[0]
    assert len(uploader.hunks) == 1
    hunk = uploader.hunks[0]
    assert hunk.old_start == 40
    assert hunk.new_start == 40
    assert hunk.header == "def upload(file):"


def test_line_numbers() -> None:
    files = parse_diff(SAMPLE)
    added = files[0].added_lines()

    # 新增第一行：旧文件第 40 行是上下文（函数内第一行），
    # 旧 41 行被删除，新 41 行 = 新增的 data = resp.json()
    # 注意：正文保留代码原有缩进（审查展示需要）
    assert added[0].content == "    data = resp.json()"
    assert added[0].new_line == 41
    assert added[1].content == '    return data.get("url")'
    assert added[1].new_line == 42
    assert added[2].new_line == 43

    removed = [line for h in files[0].hunks for line in h.lines if line.kind == "removed"]
    assert removed[0].content == '    return resp.json()["url"]'
    assert removed[0].old_line == 41  # 旧文件里的行号


def test_counts() -> None:
    files = parse_diff(SAMPLE)
    assert files[0].additions == 3
    assert files[0].deletions == 1
    assert files[1].additions == 1
    assert files[1].deletions == 1


def test_context_lines_have_both_numbers() -> None:
    files = parse_diff(SAMPLE)
    context = [line for h in files[1].hunks for line in h.lines if line.kind == "context"]
    assert context[0].content == "text"
    assert context[0].old_line == 2
    assert context[0].new_line == 2


def test_empty_and_noise() -> None:
    assert parse_diff("") == []
    assert parse_diff("commit abc\nsome text\n") == []  # 没有 diff --git 头，忽略

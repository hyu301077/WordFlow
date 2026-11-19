from copy import deepcopy

import pytest

from wordflow.coach_page import parse_page_id, read_records, send_passage


PAGE = "page_0123456789abcdef0123456789abcdef"


class FakePages:
    def __init__(self, blocks, *, sequence_guard=True):
        self.blocks = [dict(id=str(i), kind="markdown", markdown=md) for i, md in enumerate(blocks)]
        self.sequence = 0
        self.sequence_guard = sequence_guard
        self.writes = []
        self.interrupt = None

    def call(self, tool, args):
        assert args["page_id"] == PAGE and args["stream_kind"] == "content"
        if tool == "chatgpt_space.read_page":
            content = {"page_id": PAGE, "blocks": deepcopy(self.blocks)}
            if self.sequence_guard:
                content["through_sequence"] = self.sequence
            return {"metadata": {"current_sequence": self.sequence}, "content": content}

        assert tool == "chatgpt_space.edit_page"
        assert args.get("base_sequence") == (self.sequence if self.sequence_guard else None)
        self.writes.append(args)
        if self.interrupt == "concurrent":
            self.interrupt = None
            self.blocks.insert(0, {"id": "phone", "kind": "markdown", "markdown": "手机上的改动"})
            self.sequence += 1
            return {"error": {"code": "edit_conflict", "commit_status": "not_committed",
                              "recovery": {"action": "reread_and_rebuild"}}}
        if self.interrupt == "rejected":
            return {"operation_results": [{"status": "rejected"}]}
        if self.interrupt == "ignored":
            return {"operation_results": [{"status": "applied", "ignored_reason": "block_deleted"}]}
        if self.interrupt == "lost_before_commit":
            raise TimeoutError("connection lost before commit")
        op, = args["operations"]
        at = op["at"]
        assert op["op"] == "insert_markdown" and at["kind"] == "between_blocks"
        ids = [block["id"] for block in self.blocks]
        pos = ids.index(at["preceding_block_id"]) + 1 if at["preceding_block_id"] else 0
        assert at["following_block_id"] == (ids[pos] if pos < len(ids) else None)
        for index, unit in enumerate(op["block_units"]):
            block = dict(kind="markdown", markdown=unit) if isinstance(unit, str) else deepcopy(unit)
            block["id"] = f"new-{self.sequence}-{index}"
            self.blocks.insert(pos + index, block)
        self.sequence += 1
        if self.interrupt == "lost_reply":
            raise TimeoutError("connection lost after commit")
        if self.interrupt == "truncated":
            self.blocks[pos + len(op["block_units"]) - 1]["markdown"] = "```text\nwrong\n```"
        return {"operation_results": [{"status": "applied"}]}


def test_only_accepts_page_id_or_canonical_page_link():
    assert parse_page_id(PAGE) == PAGE
    assert parse_page_id(f"https://chatgpt.com/space/{PAGE}?utm_source=chatgpt.com") == PAGE
    for value in ["", f"http://chatgpt.com/space/{PAGE}", f"https://chatgpt.com@other.example/space/{PAGE}",
                  f"https://other.example/space/{PAGE}", f"https://chatgpt.com/c/{PAGE}", PAGE + "/other"]:
        with pytest.raises(ValueError):
            parse_page_id(value)


def test_existing_date_sections_keep_nested_headings_skip_material_and_other_sections():
    cloud = FakePages(["Test notes", "# 待练材料", "> # 2026-11-01", "# 2026-11-18", "One ticket, please.",
                       "## Next time", "- Try a return ticket.", "# 2026-11-19", "The practice is beginning",
                       "# Other notes", "Unrelated", "# 2026-11-99", "invalid date"])
    assert read_records(cloud, PAGE) == [
        {"block_id": "4", "day": "2026-11-18", "content": "One ticket, please."},
        {"block_id": "5", "day": "2026-11-18", "content": "## Next time"},
        {"block_id": "6", "day": "2026-11-18", "content": "- Try a return ticket."},
        {"block_id": "8", "day": "2026-11-19", "content": "The practice is beginning"},
    ]


@pytest.mark.parametrize("extra", [{"selection": {"whole_page_complete": False}}, {"view": "excerpts"}])
def test_partial_page_never_becomes_empty_snapshot(extra):
    class IncompletePage:
        def call(self, tool, args):
            return {"content": {"page_id": PAGE, "blocks": []}, **extra}

    with pytest.raises(RuntimeError, match="完整正文"):
        read_records(IncompletePage(), PAGE)


@pytest.mark.parametrize("sequence_guard", [True, False])
def test_repeat_and_multiple_passages_preserve_source_and_phone_notes(sequence_guard):
    cloud = FakePages(["# 2026-11-19", "The practice is beginning"], sequence_guard=sequence_guard)
    original = "# 2026-11-22\n\n````\nA different *kind* of train."
    send_passage(cloud, PAGE, 9, "My\n# blog", original)
    send_passage(cloud, PAGE, 9, "My\n# blog", original)
    assert len(cloud.writes) == 1
    assert cloud.blocks[0]["markdown"] == "# 待练材料"
    assert cloud.blocks[1]["markdown"] == "词流文章 9 · My # blog"
    assert cloud.blocks[2]["markdown"] == f"`````text\n{original}\n`````"
    send_passage(cloud, PAGE, 9, "My\n# blog", "Second selection.")
    assert "Second selection." in cloud.blocks[2]["markdown"]
    assert original in cloud.blocks[4]["markdown"]
    assert read_records(cloud, PAGE) == [
        {"block_id": "1", "day": "2026-11-19", "content": "The practice is beginning"},
    ]


def test_concurrent_phone_edit_and_lost_reply():
    cloud = FakePages([])
    cloud.interrupt = "concurrent"
    send_passage(cloud, PAGE, 4, "A blog", "I missed the train.")
    assert [r["base_sequence"] for r in cloud.writes] == [0, 1]
    assert cloud.blocks[-1]["markdown"] == "手机上的改动"
    cloud.interrupt = "lost_reply"
    send_passage(cloud, PAGE, 4, "A blog", "One ticket, please.")
    send_passage(cloud, PAGE, 4, "A blog", "One ticket, please.")
    assert len(cloud.writes) == 3


def test_resending_an_old_selection_makes_it_current_and_retry_is_idempotent():
    cloud = FakePages([])
    send_passage(cloud, PAGE, 9, "Blog", "Selection A.")
    send_passage(cloud, PAGE, 9, "Blog", "Selection B.")
    cloud.interrupt = "lost_before_commit"
    with pytest.raises(RuntimeError, match="未确认"):
        send_passage(cloud, PAGE, 9, "Blog", "Selection A.")
    assert cloud.blocks[2]["markdown"] == "```text\nSelection B.\n```"
    cloud.interrupt = "lost_reply"
    send_passage(cloud, PAGE, 9, "Blog", "Selection A.")
    send_passage(cloud, PAGE, 9, "Blog", "Selection A.")
    assert cloud.blocks[2]["markdown"] == "```text\nSelection A.\n```"
    assert len(cloud.writes) == 4


@pytest.mark.parametrize("outcome", ["rejected", "ignored", "truncated"])
def test_does_not_claim_success_on_unverified_write(outcome):
    cloud = FakePages([])
    cloud.interrupt = outcome
    with pytest.raises(RuntimeError):
        send_passage(cloud, PAGE, 9, "My blog", "One ticket, please.")

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkerIdentity:
    name: str
    version: str


@dataclass(frozen=True)
class TextChunk:
    start_offset: int
    end_offset: int
    text: str


class DeterministicCharacterChunker:
    identity = ChunkerIdentity(name="deterministic_chars", version="1")

    def chunk(self, text: str, *, max_chars: int) -> tuple[TextChunk, ...]:
        chunks: list[TextChunk] = []
        cursor = 0
        text_length = len(text)

        while cursor < text_length:
            while cursor < text_length and text[cursor].isspace():
                cursor += 1
            if cursor >= text_length:
                break

            start = cursor
            hard_end = min(start + max_chars, text_length)
            end = hard_end
            if hard_end < text_length and not text[hard_end].isspace():
                boundary = max(
                    text.rfind(" ", start + 1, hard_end + 1),
                    text.rfind("\n", start + 1, hard_end + 1),
                    text.rfind("\t", start + 1, hard_end + 1),
                )
                if boundary > start:
                    end = boundary

            while end > start and text[end - 1].isspace():
                end -= 1
            if end <= start:
                end = hard_end

            chunks.append(
                TextChunk(
                    start_offset=start,
                    end_offset=end,
                    text=text[start:end],
                )
            )
            cursor = max(end, start + 1)

        return tuple(chunks)

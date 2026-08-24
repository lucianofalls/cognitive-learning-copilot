"""Local-only markdown persistence for translated transcript + summary notes.

Enabled explicitly by `privacy.persist_learning_notes` in
config/settings.yaml (opt-in and off by default -- read README.md's
Privacy section and think about your own use case before turning this
on). Writes never leave this machine: no network call, no cloud sync.
Raw audio is still never written (`privacy.persist_audio` stays
false), and the raw English transcript is still not persisted verbatim
-- only the PT-BR translation and the derived summary are.

One file per session, appended to as the session progresses, so a crash
or a forced quit doesn't lose everything since the last write.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from meeting_copilot.models import MeetingSummary

_SUMMARY_SECTIONS = (
    ("facts", "Fatos"),
    ("proposals", "Propostas"),
    ("assumptions", "Suposições"),
    ("confirmed_decisions", "Decisões confirmadas"),
    ("risks", "Riscos"),
    ("open_questions", "Perguntas em aberto"),
    ("action_items", "Ações"),
)


class SessionLogWriter:
    def __init__(self, directory: Path, session_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{session_id}.md"
        header = (
            f"# Sessão {session_id}\n\n"
            f"Iniciada em {datetime.now().astimezone().isoformat(timespec='seconds')}.\n\n"
            "> Gerado localmente pelo Local English Meeting Copilot. Nunca sai desta "
            "máquina, nunca é enviado a nenhum serviço externo. Contém tradução PT-BR "
            "e notas derivadas da fala captada -- confirme se manter este arquivo é "
            "permitido pela política do seu empregador antes de compartilhá-lo.\n\n"
            "## Transcrição traduzida (PT-BR)\n\n"
        )
        self.path.write_text(header, encoding="utf-8")

    def write_translation(self, text_pt: str, pause_seconds: float | None = None) -> None:
        if not text_pt:
            return
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        pause_note = f" _(pausa de {pause_seconds:.1f}s antes deste trecho)_" if pause_seconds else ""
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(f"- **{timestamp}**{pause_note}: {text_pt}\n")

    def write_summary(self, summary: MeetingSummary) -> None:
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        lines = [f"\n## Resumo atualizado — {timestamp}\n"]
        if summary.topic:
            lines.append(f"**Tópico:** {summary.topic}\n")
        for field_name, label_pt in _SUMMARY_SECTIONS:
            items = getattr(summary, field_name)
            if items:
                lines.append(f"\n**{label_pt}:**")
                lines.extend(f"- {item}" for item in items)
        lines.append("")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

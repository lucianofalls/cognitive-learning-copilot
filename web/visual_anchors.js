// Local, offline, no-network visual pairing for Dual Coding Theory --
// a word/chunk shown alongside a genuinely relevant image/emoji is
// recalled better than text alone. Curated by hand instead of an
// external image API so it never needs a cloud-service call --
// every entry here is chosen for real semantic relevance to this
// app's actual domain (work meetings), never a generic decorative
// icon, since an irrelevant image adds novelty without adding
// retrieval value and misses the point of the theory.

const VISUAL_ANCHORS = [
  // Time / deadlines
  { keywords: ["deadline", "prazo", "due date", "até sexta", "até amanhã"], emoji: "⏰" },
  { keywords: ["schedule", "agenda", "cronograma", "calendário"], emoji: "📅" },
  { keywords: ["delay", "atraso", "atrasado", "late", "postpone", "adiar"], emoji: "🐢" },
  { keywords: ["urgent", "urgente", "asap", "priority", "prioridade"], emoji: "🚨" },

  // Agreement / disagreement / decisions
  { keywords: ["agree", "concordo", "concordar", "align", "alinhado"], emoji: "🤝" },
  { keywords: ["disagree", "discordo", "discordar", "objection", "objeção"], emoji: "🙅" },
  { keywords: ["decision", "decisão", "decide", "decidir"], emoji: "✅" },
  { keywords: ["question", "pergunta", "clarify", "clarificar", "esclarecer"], emoji: "❓" },
  { keywords: ["confused", "confuso", "unclear", "not sure", "não tenho certeza"], emoji: "🤔" },

  // Work / meetings
  { keywords: ["meeting", "reunião", "call", "chamada"], emoji: "🗓️" },
  { keywords: ["team", "equipe", "colleague", "colega"], emoji: "👥" },
  { keywords: ["task", "tarefa", "action item", "to-do"], emoji: "📝" },
  { keywords: ["blocked", "bloqueado", "blocker", "impedimento"], emoji: "🚧" },
  { keywords: ["progress", "progresso", "on track", "no prazo"], emoji: "📈" },
  { keywords: ["risk", "risco", "concern", "preocupação"], emoji: "⚠️" },
  { keywords: ["review", "revisão", "revisar", "feedback"], emoji: "🔍" },

  // Technology (matches this app's own domain glossary style)
  { keywords: ["deploy", "deployment", "release", "lançamento"], emoji: "🚀" },
  { keywords: ["bug", "erro", "issue", "problema"], emoji: "🐛" },
  { keywords: ["retry", "tentar novamente", "retentativa"], emoji: "🔁" },
  { keywords: ["server", "servidor", "backend"], emoji: "🖥️" },
  { keywords: ["database", "banco de dados"], emoji: "🗄️" },
  { keywords: ["test", "teste", "testing", "qa"], emoji: "🧪" },
  { keywords: ["security", "segurança", "auth", "autenticação"], emoji: "🔒" },
  { keywords: ["performance", "desempenho", "slow", "lento", "fast", "rápido"], emoji: "⚡" },

  // Money / business
  { keywords: ["budget", "orçamento", "cost", "custo"], emoji: "💰" },
  { keywords: ["client", "cliente", "customer"], emoji: "🧑‍💼" },
  { keywords: ["contract", "contrato", "deal", "acordo"], emoji: "📄" },

  // Emotion / tone (helps with the coach's tone/register explanations)
  { keywords: ["polite", "educado", "gentil", "please", "por favor"], emoji: "🙏" },
  { keywords: ["thanks", "obrigado", "obrigada", "grateful", "grato"], emoji: "🙏" },
  { keywords: ["sorry", "desculpa", "apologize", "desculpar"], emoji: "😅" },
  { keywords: ["congratulations", "parabéns", "well done", "great job"], emoji: "🎉" },

  // Communication verbs (common Language Coach idiomatic-chunk topics)
  { keywords: ["explain", "explicar", "explicação"], emoji: "💡" },
  { keywords: ["suggest", "sugerir", "sugestão", "propose", "propor"], emoji: "💭" },
  { keywords: ["confirm", "confirmar", "confirmação"], emoji: "👍" },
  { keywords: ["understand", "entender", "understood", "entendi"], emoji: "🧠" },
];

// Case-insensitive substring match against a curated keyword list --
// deliberately simple (no NLP/embedding lookup) so it stays instant and
// fully offline. Returns null rather than a generic fallback icon when
// nothing matches: an irrelevant "decoration" emoji is worse than none,
// per the theory's own "genuine semantic relevance, not decoration" rule.
function findVisualAnchor(text) {
  if (!text) return null;
  const normalized = text.toLowerCase();
  for (const entry of VISUAL_ANCHORS) {
    if (entry.keywords.some((kw) => normalized.includes(kw))) {
      return entry.emoji;
    }
  }
  return null;
}

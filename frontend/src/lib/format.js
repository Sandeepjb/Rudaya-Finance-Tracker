// Small formatting / color helpers to keep JSX free of nested ternaries.

export function typeColor(type) {
  if (type === "Revenue") return "#059669";
  if (type === "Cost") return "#DC2626";
  return "#D97706"; // Expense (or anything else)
}

export function signedColor(value, positiveColor = "#2563EB", negativeColor = "#B91C1C") {
  return value >= 0 ? positiveColor : negativeColor;
}

// Recharts tick style objects — memo-safe references
export const TICK_STYLE = Object.freeze({ fontSize: 11, fontFamily: "JetBrains Mono" });
export const TICK_STYLE_SM = Object.freeze({ fontSize: 10, fontFamily: "JetBrains Mono" });
export const TOOLTIP_STYLE = Object.freeze({ border: "1px solid #111827", borderRadius: 0, fontSize: 12 });
export const LEGEND_STYLE = Object.freeze({ fontSize: 12 });

export const yTickLakh = (v) => (v / 100000).toFixed(1) + "L";
export const yTickPct = (v) => v + "%";

import type { NetworkStageCell, StageProfile } from "../types";

/**
 * The one stage visual used on the results page and in staff analytics.
 * Each of the five cells shows how many practices are in place at that stage;
 * cells up to the area's stage are complete, and the first incomplete cell is
 * what holds the area at its stage. An optional network row shows the average
 * share in place per stage across all assessments.
 */
export function StageCells({ profile, network, onGapClick }: {
  profile: StageProfile;
  network?: NetworkStageCell[];
  onGapClick?: (questionId: string) => void;
}) {
  const netByStage = Object.fromEntries((network ?? []).map((c) => [c.stage, c.avg_in_place_pct]));
  return (
    <div className="stagecells">
      <div className="sc-row" role="list" aria-label={`${profile.domain_name} practices in place by stage`}>
        {profile.stages.filter((s) => s.total > 0).map((s) => {
          const complete = s.in_place === s.total;
          const blocking = profile.next_stage === s.name;
          const pct = (100 * s.in_place) / s.total;
          return (
            <div key={s.stage} role="listitem"
              className={`sc ${complete && s.stage <= profile.stage_number ? "reached" : ""} ${blocking ? "blocking" : ""}`}
              title={`${s.name}: ${s.in_place} of ${s.total} practices in place`}>
              <span className="sc-name">{s.name}</span>
              <span className="sc-meter"><span style={{ width: `${pct}%` }} /></span>
              <span className="sc-count">{s.in_place}/{s.total}</span>
              {network && netByStage[s.stage] !== undefined && (
                <span className="sc-net" title="Average share in place across the network">
                  network {Math.round(netByStage[s.stage])}%
                </span>
              )}
            </div>
          );
        })}
      </div>
      <p className="sc-summary">
        {profile.summary}
        {onGapClick && profile.blocking_gap_ids.length > 0 && (
          <> {profile.blocking_gap_ids.map((q) => (
            <button key={q} type="button" className="qref" onClick={() => onGapClick(q)}>{q}</button>
          ))}</>
        )}
      </p>
    </div>
  );
}

/** Network-only version for the aggregate view: average share in place per stage. */
export function NetworkStageCells({ cells, label }: { cells: NetworkStageCell[]; label: string }) {
  return (
    <div className="sc-row" role="list" aria-label={label}>
      {cells.map((c) => (
        <div key={c.stage} role="listitem" className="sc" title={`${c.name}: on average ${c.avg_in_place_pct}% of practices in place`}>
          <span className="sc-name">{c.name}</span>
          <span className="sc-meter"><span style={{ width: `${c.avg_in_place_pct}%` }} /></span>
          <span className="sc-count">{Math.round(c.avg_in_place_pct)}%</span>
        </div>
      ))}
    </div>
  );
}

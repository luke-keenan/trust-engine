export interface User { id: string; name: string; email: string; }

export interface Evaluation {
  id: string;
  system_id: string;
  trust_score: number;
  trusted: boolean;
  risk_tier: string;
  uncertainty: number;
  timestamp: string;
  policy_results: PolicyResult[];
}

export interface PolicyResult {
  rule_id: string;
  rule_name: string;
  sutra: string;
  result: 'pass' | 'warn' | 'fail';
  description: string;
}

export interface TrustPosture {
  system_id: string;
  current_score: number;
  trend: 'up' | 'down' | 'stable';
  evaluations: Evaluation[];
}

export interface ChartPoint { timestamp: string; trust_score: number; }

export interface Collab {
  id: string;
  name: string;
  focus: string;
  member_count: number;
  status: 'active' | 'community';
}

export interface Community {
  id: string;
  name: string;
  focus: string;
  phase: 'growing' | 'voting' | 'active' | 'dissolved';
  member_count: number;
  min_members: number;
}   
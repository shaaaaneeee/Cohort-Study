// Names for the API's types. Everything here comes from openapi.ts, which is
// generated from the backend's schema (npm run gen:types), so the study
// format is the backend's StudySpec exactly.
import type { components } from "./openapi";

type Schemas = components["schemas"];

export type StudySpec = Schemas["StudySpec"];
export type FeatureSpec = Schemas["FeatureSpec"];
export type Window = Schemas["Window"];
export type KeepIf = Schemas["KeepIf"];
export type Periodise = Schemas["Periodise"];
export type Role = FeatureSpec["role"];
export type Aggregation = FeatureSpec["aggregation"];
export type WindowUnit = Window["unit"];

export type Metadata = Schemas["Metadata"];
export type SourceInfo = Schemas["SourceInfo"];
export type Issue = Schemas["Issue"];
export type ImpliedModel = Schemas["ImpliedModel"];
export type CheckResult = Schemas["CheckResult"];
export type AttritionResult = Schemas["AttritionResult"];
export type AttritionStep = Schemas["AttritionStep"];
export type PreviewResult = Schemas["PreviewResult"];
export type AnalysisResult = Schemas["AnalysisResult"];
export type BalanceRow = Schemas["BalanceRow"];
export type ChatResult = Schemas["ChatResult"];
export type ChatRequest = Schemas["ChatRequest"];
export type ErrorBody = Schemas["ErrorBody"];
export type Health = Schemas["Health"];

export type StepName = "ask" | "cohort" | "features" | "results";

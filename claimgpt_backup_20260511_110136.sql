--
-- PostgreSQL database dump
--

\restrict QyfQP0cueUoM0OFd4Wb7wnS3IbqVKBxkO3doo1SC57prWF7LACYXzcDazIjG6CY

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: claimgpt
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO claimgpt;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.audit_logs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    actor text,
    action text,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.audit_logs OWNER TO claimgpt;

--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.chat_messages (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    role text,
    message text,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.chat_messages OWNER TO claimgpt;

--
-- Name: checkpoint_blobs; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.checkpoint_blobs (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    channel text NOT NULL,
    version text NOT NULL,
    type text NOT NULL,
    blob bytea
);


ALTER TABLE public.checkpoint_blobs OWNER TO claimgpt;

--
-- Name: checkpoint_migrations; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.checkpoint_migrations (
    v integer NOT NULL
);


ALTER TABLE public.checkpoint_migrations OWNER TO claimgpt;

--
-- Name: checkpoint_writes; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.checkpoint_writes (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    checkpoint_id text NOT NULL,
    task_id text NOT NULL,
    idx integer NOT NULL,
    channel text NOT NULL,
    type text,
    blob bytea NOT NULL,
    task_path text DEFAULT ''::text NOT NULL
);


ALTER TABLE public.checkpoint_writes OWNER TO claimgpt;

--
-- Name: checkpoints; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.checkpoints (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    checkpoint_id text NOT NULL,
    parent_checkpoint_id text,
    type text,
    checkpoint jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


ALTER TABLE public.checkpoints OWNER TO claimgpt;

--
-- Name: claims; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.claims (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    policy_id text,
    patient_id text,
    status text DEFAULT 'UPLOADED'::text NOT NULL,
    source text DEFAULT 'PATIENT'::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.claims OWNER TO claimgpt;

--
-- Name: document_validations; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.document_validations (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    document_id uuid NOT NULL,
    claim_id uuid NOT NULL,
    status text NOT NULL,
    doc_type text,
    doc_type_label text,
    is_medical integer DEFAULT 1 NOT NULL,
    patient_match text,
    confidence double precision,
    patient_name text,
    patient_id_extracted text,
    issues jsonb,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.document_validations OWNER TO claimgpt;

--
-- Name: documents; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.documents (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid NOT NULL,
    file_name text NOT NULL,
    file_type text,
    minio_path text NOT NULL,
    content_hash text NOT NULL,
    uploaded_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.documents OWNER TO claimgpt;

--
-- Name: features; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.features (
    claim_id uuid NOT NULL,
    feature_vector jsonb NOT NULL,
    generated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.features OWNER TO claimgpt;

--
-- Name: medical_codes; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.medical_codes (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    entity_id uuid,
    code text NOT NULL,
    code_system text NOT NULL,
    description text,
    confidence double precision,
    is_primary boolean DEFAULT false,
    estimated_cost double precision,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.medical_codes OWNER TO claimgpt;

--
-- Name: medical_entities; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.medical_entities (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    entity_text text NOT NULL,
    entity_type text NOT NULL,
    start_offset integer,
    end_offset integer,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.medical_entities OWNER TO claimgpt;

--
-- Name: ocr_jobs; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.ocr_jobs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    status text DEFAULT 'QUEUED'::text NOT NULL,
    total_documents integer DEFAULT 0 NOT NULL,
    processed_documents integer DEFAULT 0 NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


ALTER TABLE public.ocr_jobs OWNER TO claimgpt;

--
-- Name: ocr_results; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.ocr_results (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    document_id uuid,
    page_number integer,
    text text,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now(),
    elements jsonb
);


ALTER TABLE public.ocr_results OWNER TO claimgpt;

--
-- Name: parse_jobs; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.parse_jobs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    status text DEFAULT 'QUEUED'::text NOT NULL,
    total_documents integer DEFAULT 0 NOT NULL,
    processed_documents integer DEFAULT 0 NOT NULL,
    set_hash text,
    model_version text,
    used_fallback boolean DEFAULT false NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


ALTER TABLE public.parse_jobs OWNER TO claimgpt;

--
-- Name: parsed_fields; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.parsed_fields (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    document_id uuid,
    field_name text NOT NULL,
    field_value text,
    bounding_box jsonb,
    source_page integer,
    doc_type text,
    model_version text,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.parsed_fields OWNER TO claimgpt;

--
-- Name: predictions; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.predictions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    rejection_score double precision,
    top_reasons jsonb,
    model_name text,
    model_version text,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.predictions OWNER TO claimgpt;

--
-- Name: scan_analyses; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.scan_analyses (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    document_id uuid NOT NULL,
    claim_id uuid NOT NULL,
    scan_type text NOT NULL,
    body_part text,
    modality text,
    findings jsonb,
    impression text,
    recommendation text,
    confidence double precision,
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.scan_analyses OWNER TO claimgpt;

--
-- Name: submissions; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.submissions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    payer text,
    request_payload jsonb,
    response_payload jsonb,
    status text,
    submitted_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.submissions OWNER TO claimgpt;

--
-- Name: tpa_providers; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.tpa_providers (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    logo text DEFAULT '🏥'::text,
    provider_type text DEFAULT 'Private'::text,
    email text,
    phone text,
    website text,
    address text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.tpa_providers OWNER TO claimgpt;

--
-- Name: validations; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.validations (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    rule_id text,
    rule_name text,
    severity text,
    message text,
    passed boolean,
    evaluated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.validations OWNER TO claimgpt;

--
-- Name: workflow_jobs; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.workflow_jobs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    claim_id uuid,
    job_type text,
    status text DEFAULT 'QUEUED'::text NOT NULL,
    current_step text,
    error_message text,
    retries integer DEFAULT 0,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


ALTER TABLE public.workflow_jobs OWNER TO claimgpt;

--
-- Name: workflow_state; Type: TABLE; Schema: public; Owner: claimgpt
--

CREATE TABLE public.workflow_state (
    claim_id uuid NOT NULL,
    current_step text,
    status text NOT NULL,
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.workflow_state OWNER TO claimgpt;

--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.audit_logs (id, claim_id, actor, action, metadata, created_at) FROM stdin;
b4b9d647-fa96-46e7-926d-7afa7fe4ca67	f5e11126-9bb6-41e2-9dbb-6ca1d59a861e	ingress	CLAIM_DELETED	{"documents": ["synthea_low_7d2b32a1_history_of_tubal_ligation_situ.pdf"]}	2026-05-11 04:26:13.98469+00
760371fc-6daf-4717-b146-ec4ae8ad31c4	1a89e9f6-10d8-43f6-89bc-90e988173bcc	ingress	CLAIM_DELETED	{"documents": ["synthea_low_7d2b32a1_history_of_tubal_ligation_situ.pdf"]}	2026-05-11 04:28:09.245252+00
94ec7d77-21a0-4ef8-9bfa-0b8b50b08cd3	2955fa3a-1aa0-4437-b917-423f90841476	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "87f07bd6-bb0c-465a-8903-50690be23879", "field_names": ["table_confidence", "reconciliation_status", "parser_version", "expense_pharmacy", "expense_laboratory", "total_amount", "table_confidence", "reconciliation_status", "parser_version", "patient_name", "phone", "doctor_name", "diagnosis", "cpt_code", "cpt_code"], "model_version": "dynamic_v2", "used_fallback": false, "parser_version": "dynamic_v2", "fields_extracted": 15, "tables_extracted": 2, "originals_preserved": true}	2026-05-11 04:28:22.187671+00
8e5c5fe0-bcf5-460c-b18c-cc888ed265b2	2955fa3a-1aa0-4437-b917-423f90841476	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "2955fa3a-1aa0-4437-b917-423f90841476", "validation_failed": 2, "validation_status": "PARSED", "validation_warnings": 0}], "total_processing_seconds": 12.286945}	2026-05-11 04:28:31.321294+00
6fc85120-045e-4ade-9630-e12826edd16f	c992e786-3488-4bc0-b4d5-0da3816bdb6d	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "4cb643d3-2b42-41d9-b2a4-4934838df9bf", "field_names": ["phone", "admission_date", "discharge_date"], "model_version": "dynamic_v2", "used_fallback": false, "parser_version": "dynamic_v2", "fields_extracted": 3, "tables_extracted": 0, "originals_preserved": true}	2026-05-11 04:38:07.435595+00
dfe02937-e789-48b0-ae67-a2b73bfabaab	c992e786-3488-4bc0-b4d5-0da3816bdb6d	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "c992e786-3488-4bc0-b4d5-0da3816bdb6d", "validation_failed": 9, "validation_status": "PARSED", "validation_warnings": 5}], "total_processing_seconds": 10.112659}	2026-05-11 04:38:07.736377+00
872fdf86-b028-440d-90c2-7f584089f082	c992e786-3488-4bc0-b4d5-0da3816bdb6d	ingress	CLAIM_DELETED	{"documents": ["Hospital-Bill-Receipt-India.png"]}	2026-05-11 04:52:38.500194+00
a12ca906-2eb1-42ca-91b7-2d1f006f063f	7c8a68b2-a849-47bd-bce0-37b56cb0a32f	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "36ea0aab-d926-4f69-9b35-ec5966d3286d", "field_names": ["phone", "admission_date", "discharge_date"], "model_version": "dynamic_v2", "used_fallback": false, "parser_version": "dynamic_v2", "fields_extracted": 3, "tables_extracted": 0, "originals_preserved": true}	2026-05-11 04:53:03.209856+00
a358264e-8b20-4047-9584-85d5576ec63e	7c8a68b2-a849-47bd-bce0-37b56cb0a32f	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "7c8a68b2-a849-47bd-bce0-37b56cb0a32f", "validation_failed": 9, "validation_status": "PARSED", "validation_warnings": 5}], "total_processing_seconds": 9.946811}	2026-05-11 04:53:03.692513+00
99448242-c0fe-442c-8d8c-4b49bb5b546d	7c8a68b2-a849-47bd-bce0-37b56cb0a32f	ingress	CLAIM_DELETED	{"documents": ["Hospital-Bill-Receipt-India.png"]}	2026-05-11 04:57:05.319128+00
0598bd42-0bea-443d-a51d-7291db8d7fad	c5568d07-3434-4c94-b892-b963801e95d9	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "2b16defa-e308-4709-8429-83d3a989d83c", "field_names": ["patient_name", "date_of_birth", "age", "gender", "address", "address", "address", "address", "phone", "email", "policy_number", "claim_number", "member_id", "insurer", "hospital_name", "admission_date", "discharge_date", "General Ward – 1 Days", "Plain X-ray of mandible (procedure)", "Specialist – 3 visits", "Acetaminophen 325 MG / oxyCODO, Naproxen sodium 220 MG Or...", "Blood tests, panels", "Nursing care – 1 days", "Surgical consumables, IV lines", "Admin, Food, Transport", "diagnosis", "doctor_name", "phone", "insurer", "cpt_code"], "model_version": "heuristic-v2", "used_fallback": true, "fields_extracted": 30, "originals_preserved": true}	2026-05-11 04:57:21.985515+00
f9baf15b-38b4-4edf-8610-4ef00ea9cb65	c5568d07-3434-4c94-b892-b963801e95d9	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "c5568d07-3434-4c94-b892-b963801e95d9", "validation_failed": 1, "validation_status": "PARSED", "validation_warnings": 1}], "total_processing_seconds": 11.968507}	2026-05-11 04:57:26.123814+00
e23f232d-a310-4792-affc-c45729b71572	2ba4f78a-c552-47df-8372-3a62cde2e4d1	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "8697743d-7251-4039-a1f9-99a2c8b80c66", "field_names": ["Room Charges", "Surgery Charges", "Anesthesia Charges", "patient_name", "phone", "email", "patient_id", "admission_date", "discharge_date", "hospital_name"], "model_version": "heuristic-v2", "used_fallback": true, "fields_extracted": 10, "originals_preserved": true}	2026-05-11 04:57:53.549762+00
81831387-355e-465d-8eaf-00d9032c675b	2ba4f78a-c552-47df-8372-3a62cde2e4d1	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "2ba4f78a-c552-47df-8372-3a62cde2e4d1", "validation_failed": 6, "validation_status": "PARSED", "validation_warnings": 3}], "total_processing_seconds": 9.904282}	2026-05-11 04:57:53.843348+00
5f7db7dc-a624-4cc3-888b-ec6491e6fe5a	647da5fa-9272-4ab8-81f0-b6b57a1886a3	parser	DATA_EXTRACTED_FROM_COPY	{"job_id": "7d684ebc-f365-4d54-9e7e-21fbdbb8eb41", "field_names": ["patient_name", "date_of_birth", "age", "gender", "address", "address", "address", "address", "phone", "email", "policy_number", "claim_number", "member_id", "insurer", "hospital_name", "admission_date", "discharge_date", "General Ward – 1 Days", "Medication reconciliation (procedure)", "Specialist – 3 visits", "lisinopril 10 MG Oral Tablet", "Glucose [Mass/volume] in , Urea nitrogen [Mass/volum", "Nursing care – 1 days", "Surgical consumables, IV lines", "Admin, Food, Transport", "diagnosis", "doctor_name", "cpt_code"], "model_version": "heuristic-v2", "used_fallback": true, "fields_extracted": 28, "originals_preserved": true}	2026-05-11 05:01:21.517611+00
461e50c5-0c03-4c5b-a011-8c3bf8d0ccc3	647da5fa-9272-4ab8-81f0-b6b57a1886a3	workflow	PIPELINE_COMPLETED	{"final_results": [{"claim_id": "647da5fa-9272-4ab8-81f0-b6b57a1886a3", "validation_failed": 1, "validation_status": "PARSED", "validation_warnings": 1}], "total_processing_seconds": 56.170866}	2026-05-11 05:01:25.785763+00
\.


--
-- Data for Name: chat_messages; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.chat_messages (id, claim_id, role, message, created_at) FROM stdin;
\.


--
-- Data for Name: checkpoint_blobs; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob) FROM stdin;
\.


--
-- Data for Name: checkpoint_migrations; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.checkpoint_migrations (v) FROM stdin;
0
1
2
3
4
5
6
7
8
9
\.


--
-- Data for Name: checkpoint_writes; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path) FROM stdin;
\.


--
-- Data for Name: checkpoints; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) FROM stdin;
\.


--
-- Data for Name: claims; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.claims (id, policy_id, patient_id, status, source, created_at, updated_at) FROM stdin;
2955fa3a-1aa0-4437-b917-423f90841476	\N	\N	COMPLETED	PATIENT	2026-05-11 04:28:18.991915+00	2026-05-11 04:28:31.292996+00
c5568d07-3434-4c94-b892-b963801e95d9	\N	\N	COMPLETED	PATIENT	2026-05-11 04:57:14.104922+00	2026-05-11 04:57:26.056237+00
2ba4f78a-c552-47df-8372-3a62cde2e4d1	\N	\N	COMPLETED	PATIENT	2026-05-11 04:57:43.918767+00	2026-05-11 04:57:53.822703+00
647da5fa-9272-4ab8-81f0-b6b57a1886a3	\N	\N	COMPLETED	PATIENT	2026-05-11 05:00:29.575275+00	2026-05-11 05:01:25.749786+00
\.


--
-- Data for Name: document_validations; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.document_validations (id, document_id, claim_id, status, doc_type, doc_type_label, is_medical, patient_match, confidence, patient_name, patient_id_extracted, issues, metadata, created_at) FROM stdin;
\.


--
-- Data for Name: documents; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.documents (id, claim_id, file_name, file_type, minio_path, content_hash, uploaded_at) FROM stdin;
62a283f3-8530-4aac-a8cd-96371e9cd1eb	2955fa3a-1aa0-4437-b917-423f90841476	synthea_low_7d2b32a1_history_of_tubal_ligation_situ.pdf	application/pdf	C:\\Project\\ClaimGPT\\services\\ingress\\storage\\raw\\2955fa3a-1aa0-4437-b917-423f90841476.pdf	af7e73fb0802abf3e90b8ec7efe77c5aeb5a749a91696a3d2a68667462ae1d9e	2026-05-11 04:28:18.991915+00
f248abf7-7f79-4b19-860c-dbf82a30a46a	c5568d07-3434-4c94-b892-b963801e95d9	synthea_low_27df3da3_fracture_of_mandible_disorder.pdf	application/pdf	C:\\Project\\ClaimGPT\\services\\ingress\\storage\\raw\\c5568d07-3434-4c94-b892-b963801e95d9.pdf	b20ccb45c4c23978b2115f45109b348b8103a5c145646683d701e535cd796316	2026-05-11 04:57:14.104922+00
2fc2a78d-3682-481b-8c0b-207d1aff3c67	2ba4f78a-c552-47df-8372-3a62cde2e4d1	Hospital-Bill-Receipt-India.png	image/png	C:\\Project\\ClaimGPT\\services\\ingress\\storage\\raw\\2ba4f78a-c552-47df-8372-3a62cde2e4d1.png	171b21d0e9c5b45aa42c9b1477e34b0f64bc2dfd408458fd4b4c6b55f0249143	2026-05-11 04:57:43.918767+00
e7d1ff76-6929-4f78-a588-b39a121f3155	647da5fa-9272-4ab8-81f0-b6b57a1886a3	synthea_low_229202ec_medication_review_due_situatio.pdf	application/pdf	C:\\Project\\ClaimGPT\\services\\ingress\\storage\\raw\\647da5fa-9272-4ab8-81f0-b6b57a1886a3.pdf	c68ff861d4f8518a884ff9736d749af0d6fd01ad5ad3e16000428adb33dfce86	2026-05-11 05:00:29.575275+00
\.


--
-- Data for Name: features; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.features (claim_id, feature_vector, generated_at) FROM stdin;
2955fa3a-1aa0-4437-b917-423f90841476	{"has_surgery": 0, "has_provider": 1, "num_entities": 3, "has_diagnosis": 1, "num_cpt_codes": 2, "num_icd_codes": 1, "length_of_stay": 0.0, "has_primary_icd": 1, "has_patient_name": 1, "has_service_date": 0, "has_total_amount": 1, "is_icu_admission": 0, "patient_age_norm": 0.0, "total_amount_log": 9.19624144759668, "has_policy_number": 0, "num_parsed_fields": 15, "amount_per_cpt_log": 8.503195681772384, "surgery_cost_ratio": 0.0, "num_diagnosis_types": 1, "has_blood_transfusion": 0, "claim_to_insured_ratio": 0.0, "num_expense_categories": 0.0, "has_secondary_diagnosis": 0}	2026-05-11 04:28:22.61815+00
c5568d07-3434-4c94-b892-b963801e95d9	{"has_surgery": 0, "has_provider": 1, "num_entities": 2, "has_diagnosis": 1, "num_cpt_codes": 1, "num_icd_codes": 2, "length_of_stay": 0.0, "has_primary_icd": 1, "has_patient_name": 1, "has_service_date": 1, "has_total_amount": 0, "is_icu_admission": 0, "patient_age_norm": 0.59, "total_amount_log": 0.0, "has_policy_number": 1, "num_parsed_fields": 30, "amount_per_cpt_log": 0.0, "surgery_cost_ratio": 0.0, "num_diagnosis_types": 1, "has_blood_transfusion": 0, "claim_to_insured_ratio": 0.0, "num_expense_categories": 0.0, "has_secondary_diagnosis": 0}	2026-05-11 04:57:22.534096+00
2ba4f78a-c552-47df-8372-3a62cde2e4d1	{"has_surgery": 0, "has_provider": 1, "num_entities": 0, "has_diagnosis": 0, "num_cpt_codes": 0, "num_icd_codes": 0, "length_of_stay": 4.0, "has_primary_icd": 0, "has_patient_name": 1, "has_service_date": 1, "has_total_amount": 0, "is_icu_admission": 0, "patient_age_norm": 0.0, "total_amount_log": 0.0, "has_policy_number": 0, "num_parsed_fields": 10, "amount_per_cpt_log": 0.0, "surgery_cost_ratio": 0.0, "num_diagnosis_types": 0, "has_blood_transfusion": 0, "claim_to_insured_ratio": 0.0, "num_expense_categories": 0.0, "has_secondary_diagnosis": 0}	2026-05-11 04:57:53.686983+00
647da5fa-9272-4ab8-81f0-b6b57a1886a3	{"has_surgery": 0, "has_provider": 1, "num_entities": 2, "has_diagnosis": 1, "num_cpt_codes": 1, "num_icd_codes": 1, "length_of_stay": 0.0, "has_primary_icd": 1, "has_patient_name": 1, "has_service_date": 1, "has_total_amount": 0, "is_icu_admission": 0, "patient_age_norm": 0.59, "total_amount_log": 0.0, "has_policy_number": 1, "num_parsed_fields": 28, "amount_per_cpt_log": 0.0, "surgery_cost_ratio": 0.0, "num_diagnosis_types": 1, "has_blood_transfusion": 0, "claim_to_insured_ratio": 0.0, "num_expense_categories": 0.0, "has_secondary_diagnosis": 0}	2026-05-11 05:01:21.929558+00
\.


--
-- Data for Name: medical_codes; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.medical_codes (id, claim_id, entity_id, code, code_system, description, confidence, is_primary, estimated_cost, created_at) FROM stdin;
692d1d68-ee9e-4ff9-920c-d454d3b0a2e9	2955fa3a-1aa0-4437-b917-423f90841476	b985e47f-3574-41f0-bfd1-c0eeb1688cc2	I21.9	ICD10	Ref: CLM-2026-138175 FORM MA FAMILY  0 027802465 prior 02780 claim(s) HOSPITAL   39% INPATIENT of INC. sum insured	0.9	t	28000	2026-05-11 04:28:22.38591+00
f75f4f84-c0f4-4f64-993e-5b88ef4a9e1c	2955fa3a-1aa0-4437-b917-423f90841476	4b62ad5f-d54b-4cc3-b2be-20cc4fe23aca	02780	CPT	Taunton, Massachusetts	0.95	t	\N	2026-05-11 04:28:22.38591+00
e76be4ce-0359-41f1-be07-f334b11202aa	2955fa3a-1aa0-4437-b917-423f90841476	0877f96c-5049-4d85-a47b-95b2c0293278	24278	CPT	No.: MCI-	0.95	f	\N	2026-05-11 04:28:22.38591+00
6fc419a2-35c4-48f4-adbb-33e3d8fc2687	c5568d07-3434-4c94-b892-b963801e95d9	e1e3bf15-2528-4abd-b8ce-f8a97b5a1653	M81.0	ICD10	Fracture of mandible (disorder)	0.9	t	3500	2026-05-11 04:57:22.228227+00
2e721dd2-db8d-419d-b53f-1e2271745b22	c5568d07-3434-4c94-b892-b963801e95d9	e1e3bf15-2528-4abd-b8ce-f8a97b5a1653	S22.31XA	ICD10	Fracture of mandible (disorder)	0.9	f	4500	2026-05-11 04:57:22.228227+00
eb0be427-d14c-4cd6-ba6f-410a34d670c9	c5568d07-3434-4c94-b892-b963801e95d9	ffe762b5-6d46-4ef5-9d1b-79fe7b2d08d6	02148	CPT	Address: 600 Zieme Vista Unit 57, Malden, Massachusetts	0.95	t	\N	2026-05-11 04:57:22.228227+00
8913a7c2-636c-43c0-80d5-40a3a7df88ff	647da5fa-9272-4ab8-81f0-b6b57a1886a3	ff0f4550-c419-46b1-977e-72d8fd038fd4	D65	ICD10	Medication review due (situation)	0.9	t	15000	2026-05-11 05:01:21.697129+00
62bc27c8-6003-4c8b-863c-c00eca8f3b22	647da5fa-9272-4ab8-81f0-b6b57a1886a3	7745b468-1527-4bdb-bc42-6c53374053ae	00000	CPT	Address: 619 Kshlerin Park, Shrewsbury, Massachusetts	0.95	t	\N	2026-05-11 05:01:21.697129+00
\.


--
-- Data for Name: medical_entities; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.medical_entities (id, claim_id, entity_text, entity_type, start_offset, end_offset, confidence, created_at) FROM stdin;
b985e47f-3574-41f0-bfd1-c0eeb1688cc2	2955fa3a-1aa0-4437-b917-423f90841476	Ref: CLM-2026-138175 FORM MA FAMILY  0 027802465 prior 02780 claim(s) HOSPITAL   39% INPATIENT of INC. sum insured	DIAGNOSIS	-1	-1	0.9	2026-05-11 04:28:22.38591+00
4b62ad5f-d54b-4cc3-b2be-20cc4fe23aca	2955fa3a-1aa0-4437-b917-423f90841476	02780	PROCEDURE	380	385	0.9	2026-05-11 04:28:22.38591+00
0877f96c-5049-4d85-a47b-95b2c0293278	2955fa3a-1aa0-4437-b917-423f90841476	24278	PROCEDURE	1122	1127	0.9	2026-05-11 04:28:22.38591+00
e1e3bf15-2528-4abd-b8ce-f8a97b5a1653	c5568d07-3434-4c94-b892-b963801e95d9	Fracture of mandible (disorder)	DIAGNOSIS	2257	2288	0.9	2026-05-11 04:57:22.228227+00
ffe762b5-6d46-4ef5-9d1b-79fe7b2d08d6	c5568d07-3434-4c94-b892-b963801e95d9	02148	PROCEDURE	394	399	0.9	2026-05-11 04:57:22.228227+00
ff0f4550-c419-46b1-977e-72d8fd038fd4	647da5fa-9272-4ab8-81f0-b6b57a1886a3	Medication review due (situation)	DIAGNOSIS	2180	2213	0.9	2026-05-11 05:01:21.697129+00
7745b468-1527-4bdb-bc42-6c53374053ae	647da5fa-9272-4ab8-81f0-b6b57a1886a3	00000	PROCEDURE	379	384	0.9	2026-05-11 05:01:21.697129+00
\.


--
-- Data for Name: ocr_jobs; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.ocr_jobs (id, claim_id, status, total_documents, processed_documents, error_message, created_at, completed_at) FROM stdin;
f12ddef2-5dc6-401d-820d-54a67fcaad41	2955fa3a-1aa0-4437-b917-423f90841476	COMPLETED	1	1	\N	2026-05-11 04:28:19.605754+00	\N
e8d7cb91-e9c8-460b-bbe8-308d3b692722	c5568d07-3434-4c94-b892-b963801e95d9	COMPLETED	1	1	\N	2026-05-11 04:57:15.419851+00	\N
3af01ba1-e639-4ed9-9ba3-1f49ea1be7bd	2ba4f78a-c552-47df-8372-3a62cde2e4d1	COMPLETED	1	1	\N	2026-05-11 04:57:44.047853+00	\N
db342fee-74ea-4d3b-9f66-4d7548d3f74c	647da5fa-9272-4ab8-81f0-b6b57a1886a3	COMPLETED	1	1	\N	2026-05-11 05:00:30.120401+00	\N
\.


--
-- Data for Name: ocr_results; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.ocr_results (id, document_id, page_number, text, confidence, created_at, elements) FROM stdin;
3904c506-e6d9-4a97-a2a6-d4d6879ced00	62a283f3-8530-4aac-a8cd-96371e9cd1eb	1	MEDICAL\nINSURANCE\nCLAIM\nFORM\nMORTON\nHOSPITAL\nA\nSTEWARD\nFAMILY\nHOSPITAL\nINC.\n|\nClaim\nRef:\nCLM-2026-138175\n|\nINPATIENT\nRISK\nCLASSIFICATION:\nLOW\nRISK\nRoutine\nadmission\n|\n1\ndiagnosis\n|\n0\nprior\nclaim(s)\n|\n39%\nof\nsum\ninsured\n1.\nPATIENT\nINFORMATION\nPatient\nName:\nMrs.\nJoie561\nVolkman526\nDate\nof\nBirth:\n09-06-1976\nGender:\nFemale\nAge:\n49\nYears\nAddress:\n289\nFay\nRow,\nTaunton,\nMassachusetts\n02780\nPhone:\n+1-176-505-7490\nEmail:\njoie561.volkman526@hotmail.com\nBlood\nGroup:\nB-\n2.\nINSURANCE\nINFORMATION\nInsurance\nProvider:\nMedicaid\nPolicy\nNumber:\nPOL-SH-2025-572387\nMember\nID:\nMEM-89699989\nGroup\nNumber:\nGRP-2025-337\nPolicy\nType:\nIndividual\nSum\nInsured:\nRs.\n200,000\nPolicy\nStart\nDate:\n01-01-2025\nPolicy\nEnd\nDate:\n31-12-2025\nPrevious\nClaims:\nNone\nTotal\nClaimed:\nRs.\n0\nTPA:\nVipul\nMedcorp\nTPA\n3.\nHOSPITALIZATION\nDETAILS\nHospital\nName:\nMORTON\nHOSPITAL\nA\nSTEWARD\nFAMILY\nHOSPITAL\nINC.\nRegistration:\nMORT-REG-5720\nAddress:\n88\nWASHINGTON\nST,\nTAUNTON\nMA\n027802465\nContact:\n6174194772\nDate\nof\nAdmission:\n08-07-2001\nDate\nof\nDischarge:\n09-07-2001\nTotal\nDays:\n1\nDays\n(General\nWard)\nWard\nType:\nGeneral\nWard	99	2026-05-11 04:28:19.751+00	[{"bbox": [175.53679, 61.41770000000008, 239.30679, 75.41770000000008], "page": 1, "text": "MEDICAL", "source": "pdfplumber", "confidence": null}, {"bbox": [243.19879, 61.41770000000008, 326.41479000000004, 75.41770000000008], "page": 1, "text": "INSURANCE", "source": "pdfplumber", "confidence": null}, {"bbox": [330.30679, 61.41770000000008, 374.63079, 75.41770000000008], "page": 1, "text": "CLAIM", "source": "pdfplumber", "confidence": null}, {"bbox": [378.52279, 61.41770000000008, 419.73879, 75.41770000000008], "page": 1, "text": "FORM", "source": "pdfplumber", "confidence": null}, {"bbox": [96.1028, 80.27920000000006, 133.8768, 88.77920000000006], "page": 1, "text": "MORTON", "source": "pdfplumber", "confidence": null}, {"bbox": [136.2398, 80.27920000000006, 178.2808, 88.77920000000006], "page": 1, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [180.6438, 80.27920000000006, 186.3133, 88.77920000000006], "page": 1, "text": "A", "source": "pdfplumber", "confidence": null}, {"bbox": [188.6763, 80.27920000000006, 231.1763, 88.77920000000006], "page": 1, "text": "STEWARD", "source": "pdfplumber", "confidence": null}, {"bbox": [233.5393, 80.27920000000006, 264.2413, 88.77920000000006], "page": 1, "text": "FAMILY", "source": "pdfplumber", "confidence": null}, {"bbox": [266.60429999999997, 80.27920000000006, 308.6453, 88.77920000000006], "page": 1, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [311.00829999999996, 80.27920000000006, 328.0083, 88.77920000000006], "page": 1, "text": "INC.", "source": "pdfplumber", "confidence": null}, {"bbox": [330.3713, 80.27920000000006, 332.5813, 88.77920000000006], "page": 1, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [334.9443, 80.27920000000006, 356.66179999999997, 88.77920000000006], "page": 1, "text": "Claim", "source": "pdfplumber", "confidence": null}, {"bbox": [359.02479999999997, 80.27920000000006, 374.61379999999997, 88.77920000000006], "page": 1, "text": "Ref:", "source": "pdfplumber", "confidence": null}, {"bbox": [376.97679999999997, 80.27920000000006, 447.8412999999999, 88.77920000000006], "page": 1, "text": "CLM-2026-138175", "source": "pdfplumber", "confidence": null}, {"bbox": [450.2042999999999, 80.27920000000006, 452.41429999999986, 88.77920000000006], "page": 1, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [454.77729999999985, 80.27920000000006, 499.17279999999994, 88.77920000000006], "page": 1, "text": "INPATIENT", "source": "pdfplumber", "confidence": null}, {"bbox": [69.56542999999999, 120.55590000000007, 91.06643, 129.55590000000007], "page": 1, "text": "RISK", "source": "pdfplumber", "confidence": null}, {"bbox": [93.56842999999999, 120.55590000000007, 172.06643000000003, 129.55590000000007], "page": 1, "text": "CLASSIFICATION:", "source": "pdfplumber", "confidence": null}, {"bbox": [174.56842999999998, 120.55590000000007, 195.56543, 129.55590000000007], "page": 1, "text": "LOW", "source": "pdfplumber", "confidence": null}, {"bbox": [198.06742999999997, 120.55590000000007, 219.56842999999998, 129.55590000000007], "page": 1, "text": "RISK", "source": "pdfplumber", "confidence": null}, {"bbox": [274.96906, 120.34889999999996, 302.53706, 128.34889999999996], "page": 1, "text": "Routine", "source": "pdfplumber", "confidence": null}, {"bbox": [304.76106000000004, 120.34889999999996, 340.76906, 128.34889999999996], "page": 1, "text": "admission", "source": "pdfplumber", "confidence": null}, {"bbox": [342.99306, 120.34889999999996, 345.07306, 128.34889999999996], "page": 1, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [347.29706000000004, 120.34889999999996, 351.74506, 128.34889999999996], "page": 1, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [353.96906, 120.34889999999996, 387.76106000000004, 128.34889999999996], "page": 1, "text": "diagnosis", "source": "pdfplumber", "confidence": null}, {"bbox": [389.98506000000003, 120.34889999999996, 392.06506, 128.34889999999996], "page": 1, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [394.28906000000006, 120.34889999999996, 398.73706000000004, 128.34889999999996], "page": 1, "text": "0", "source": "pdfplumber", "confidence": null}, {"bbox": [400.96106000000003, 120.34889999999996, 416.96106000000003, 128.34889999999996], "page": 1, "text": "prior", "source": "pdfplumber", "confidence": null}, {"bbox": [419.18506, 120.34889999999996, 447.17706, 128.34889999999996], "page": 1, "text": "claim(s)", "source": "pdfplumber", "confidence": null}, {"bbox": [449.40106000000003, 120.34889999999996, 451.48106, 128.34889999999996], "page": 1, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [453.70506, 120.34889999999996, 469.71306000000004, 128.34889999999996], "page": 1, "text": "39%", "source": "pdfplumber", "confidence": null}, {"bbox": [471.93706, 120.34889999999996, 478.60906, 128.34889999999996], "page": 1, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [480.83306, 120.34889999999996, 495.94506, 128.34889999999996], "page": 1, "text": "sum", "source": "pdfplumber", "confidence": null}, {"bbox": [498.16905999999994, 120.34889999999996, 524.40106, 128.34889999999996], "page": 1, "text": "insured", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 158.5222, 57.191689999999994, 166.5222], "page": 1, "text": "1.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 158.5222, 93.63969, 166.5222], "page": 1, "text": "PATIENT", "source": "pdfplumber", "confidence": null}, {"bbox": [95.86368999999999, 158.5222, 152.30369000000002, 166.5222], "page": 1, "text": "INFORMATION", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 179.41870000000006, 75.52468999999999, 186.91870000000006], "page": 1, "text": "Patient", "source": "pdfplumber", "confidence": null}, {"bbox": [77.60969, 179.41870000000006, 100.52969, 186.91870000000006], "page": 1, "text": "Name:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 179.7292000000001, 261.90549000000004, 188.7292000000001], "page": 1, "text": "Mrs.", "source": "pdfplumber", "confidence": null}, {"bbox": [264.40749, 179.7292000000001, 295.92549, 188.7292000000001], "page": 1, "text": "Joie561", "source": "pdfplumber", "confidence": null}, {"bbox": [298.42749, 179.7292000000001, 348.44949, 188.7292000000001], "page": 1, "text": "Volkman526", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 199.41870000000006, 66.77219, 206.91870000000006], "page": 1, "text": "Date", "source": "pdfplumber", "confidence": null}, {"bbox": [68.85719, 199.41870000000006, 75.93719, 206.91870000000006], "page": 1, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [78.02219, 199.41870000000006, 98.01719, 206.91870000000006], "page": 1, "text": "Birth:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 199.7292000000001, 290.43549, 208.7292000000001], "page": 1, "text": "09-06-1976", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 219.41870000000006, 79.27468999999999, 226.91870000000006], "page": 1, "text": "Gender:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 219.7292000000001, 274.41549000000003, 228.7292000000001], "page": 1, "text": "Female", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 239.41870000000006, 67.18469, 246.91870000000006], "page": 1, "text": "Age:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 239.7292000000001, 254.41749, 248.7292000000001], "page": 1, "text": "49", "source": "pdfplumber", "confidence": null}, {"bbox": [256.91949, 239.7292000000001, 280.42749000000003, 248.7292000000001], "page": 1, "text": "Years", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 259.41870000000006, 83.02468999999999, 266.91870000000006], "page": 1, "text": "Address:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 259.7292000000001, 259.42149, 268.7292000000001], "page": 1, "text": "289", "source": "pdfplumber", "confidence": null}, {"bbox": [261.92349, 259.7292000000001, 276.92649, 268.7292000000001], "page": 1, "text": "Fay", "source": "pdfplumber", "confidence": null}, {"bbox": [279.42849, 259.7292000000001, 299.93049, 268.7292000000001], "page": 1, "text": "Row,", "source": "pdfplumber", "confidence": null}, {"bbox": [302.43249000000003, 259.7292000000001, 337.95549, 268.7292000000001], "page": 1, "text": "Taunton,", "source": "pdfplumber", "confidence": null}, {"bbox": [340.45749, 259.7292000000001, 400.47849, 268.7292000000001], "page": 1, "text": "Massachusetts", "source": "pdfplumber", "confidence": null}, {"bbox": [402.98049000000003, 259.7292000000001, 428.00049, 268.7292000000001], "page": 1, "text": "02780", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 279.41870000000006, 75.93719, 286.91870000000006], "page": 1, "text": "Phone:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 279.7292000000001, 313.70049, 288.7292000000001], "page": 1, "text": "+1-176-505-7490", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 299.41870000000006, 73.02719, 306.91870000000006], "page": 1, "text": "Email:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 299.7292000000001, 382.0914900000001, 308.7292000000001], "page": 1, "text": "joie561.volkman526@hotmail.com", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 319.41870000000006, 71.76718999999999, 326.91870000000006], "page": 1, "text": "Blood", "source": "pdfplumber", "confidence": null}, {"bbox": [73.85219, 319.41870000000006, 98.84969, 326.91870000000006], "page": 1, "text": "Group:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 319.7292000000001, 253.40949, 328.7292000000001], "page": 1, "text": "B-", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 351.86080000000004, 57.191689999999994, 359.86080000000004], "page": 1, "text": "2.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 351.86080000000004, 106.96768999999999, 359.86080000000004], "page": 1, "text": "INSURANCE", "source": "pdfplumber", "confidence": null}, {"bbox": [109.19169, 351.86080000000004, 165.63169000000002, 359.86080000000004], "page": 1, "text": "INFORMATION", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 372.75730000000004, 85.94968999999999, 380.25730000000004], "page": 1, "text": "Insurance", "source": "pdfplumber", "confidence": null}, {"bbox": [88.03469, 372.75730000000004, 120.95969000000001, 380.25730000000004], "page": 1, "text": "Provider:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 373.06780000000003, 280.41849, 382.06780000000003], "page": 1, "text": "Medicaid", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 392.75730000000004, 72.61469000000001, 400.25730000000004], "page": 1, "text": "Policy", "source": "pdfplumber", "confidence": null}, {"bbox": [74.69969, 392.75730000000004, 105.53219000000001, 400.25730000000004], "page": 1, "text": "Number:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 393.06780000000003, 333.95049000000006, 402.06780000000003], "page": 1, "text": "POL-SH-2025-572387", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 412.75730000000004, 79.27469, 420.25730000000004], "page": 1, "text": "Member", "source": "pdfplumber", "confidence": null}, {"bbox": [81.35969, 412.75730000000004, 91.35719, 420.25730000000004], "page": 1, "text": "ID:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 413.06780000000003, 308.43549, 422.06780000000003], "page": 1, "text": "MEM-89699989", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 432.75730000000004, 73.01968999999998, 440.25730000000004], "page": 1, "text": "Group", "source": "pdfplumber", "confidence": null}, {"bbox": [75.10468999999999, 432.75730000000004, 105.93718999999999, 440.25730000000004], "page": 1, "text": "Number:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 433.06780000000003, 304.93449000000004, 442.06780000000003], "page": 1, "text": "GRP-2025-337", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 452.75730000000004, 72.61469000000001, 460.25730000000004], "page": 1, "text": "Policy", "source": "pdfplumber", "confidence": null}, {"bbox": [74.69969, 452.75730000000004, 94.70219, 460.25730000000004], "page": 1, "text": "Type:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 453.06780000000003, 282.42549, 462.06780000000003], "page": 1, "text": "Individual", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 472.75730000000004, 66.77219, 480.25730000000004], "page": 1, "text": "Sum", "source": "pdfplumber", "confidence": null}, {"bbox": [68.85719, 472.75730000000004, 98.44469000000001, 480.25730000000004], "page": 1, "text": "Insured:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 473.06780000000003, 257.90949, 482.06780000000003], "page": 1, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [260.41149, 473.06780000000003, 292.93749, 482.06780000000003], "page": 1, "text": "200,000", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 492.75730000000004, 72.61469000000001, 500.25730000000004], "page": 1, "text": "Policy", "source": "pdfplumber", "confidence": null}, {"bbox": [74.69969, 492.75730000000004, 91.78469000000001, 500.25730000000004], "page": 1, "text": "Start", "source": "pdfplumber", "confidence": null}, {"bbox": [93.86969, 492.75730000000004, 112.61969000000002, 500.25730000000004], "page": 1, "text": "Date:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 493.06780000000003, 290.43549, 502.06780000000003], "page": 1, "text": "01-01-2025", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 512.7573, 72.61469000000001, 520.2573], "page": 1, "text": "Policy", "source": "pdfplumber", "confidence": null}, {"bbox": [74.69969, 512.7573, 88.86719000000001, 520.2573], "page": 1, "text": "End", "source": "pdfplumber", "confidence": null}, {"bbox": [90.95219, 512.7573, 109.70219000000002, 520.2573], "page": 1, "text": "Date:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 513.0678, 290.43549, 522.0678], "page": 1, "text": "31-12-2025", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 532.7573, 82.19968999999999, 540.2573], "page": 1, "text": "Previous", "source": "pdfplumber", "confidence": null}, {"bbox": [84.28469, 532.7573, 111.37469, 540.2573], "page": 1, "text": "Claims:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 533.0678, 265.91949, 542.0678], "page": 1, "text": "None", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 552.7573, 68.43718999999999, 560.2573], "page": 1, "text": "Total", "source": "pdfplumber", "confidence": null}, {"bbox": [70.52219, 552.7573, 102.19469, 560.2573], "page": 1, "text": "Claimed:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 553.0678, 257.90949, 562.0678], "page": 1, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [260.41149, 553.0678, 265.41549000000003, 562.0678], "page": 1, "text": "0", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 572.7573, 68.01719, 580.2573], "page": 1, "text": "TPA:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 573.0678, 264.41649, 582.0678], "page": 1, "text": "Vipul", "source": "pdfplumber", "confidence": null}, {"bbox": [266.91849, 573.0678, 301.92849, 582.0678], "page": 1, "text": "Medcorp", "source": "pdfplumber", "confidence": null}, {"bbox": [304.43049, 573.0678, 321.93549, 582.0678], "page": 1, "text": "TPA", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 605.1993, 57.191689999999994, 613.1993], "page": 1, "text": "3.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 605.1993, 131.86369000000002, 613.1993], "page": 1, "text": "HOSPITALIZATION", "source": "pdfplumber", "confidence": null}, {"bbox": [134.08769, 605.1993, 168.31169000000003, 613.1993], "page": 1, "text": "DETAILS", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 626.0958400000001, 80.10718999999999, 633.5958400000001], "page": 1, "text": "Hospital", "source": "pdfplumber", "confidence": null}, {"bbox": [82.19219, 626.0958400000001, 105.11219, 633.5958400000001], "page": 1, "text": "Name:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 626.40634, 284.40549, 635.40634], "page": 1, "text": "MORTON", "source": "pdfplumber", "confidence": null}, {"bbox": [286.90749, 626.40634, 331.42149, 635.40634], "page": 1, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [333.92349, 626.40634, 339.92649, 635.40634], "page": 1, "text": "A", "source": "pdfplumber", "confidence": null}, {"bbox": [342.42849, 626.40634, 387.42848999999995, 635.40634], "page": 1, "text": "STEWARD", "source": "pdfplumber", "confidence": null}, {"bbox": [389.93048999999996, 626.40634, 422.43848999999994, 635.40634], "page": 1, "text": "FAMILY", "source": "pdfplumber", "confidence": null}, {"bbox": [424.94049, 626.40634, 469.45449, 635.40634], "page": 1, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [471.95649000000003, 626.40634, 489.95649, 635.40634], "page": 1, "text": "INC.", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 646.0958400000001, 96.77219, 653.5958400000001], "page": 1, "text": "Registration:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 646.40634, 316.41849, 655.40634], "page": 1, "text": "MORT-REG-5720", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 666.0958400000001, 83.02468999999999, 673.5958400000001], "page": 1, "text": "Address:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 666.40634, 254.41749, 675.40634], "page": 1, "text": "88", "source": "pdfplumber", "confidence": null}, {"bbox": [256.91949, 666.40634, 318.92049000000003, 675.40634], "page": 1, "text": "WASHINGTON", "source": "pdfplumber", "confidence": null}, {"bbox": [321.42249000000004, 666.40634, 335.42649, 675.40634], "page": 1, "text": "ST,", "source": "pdfplumber", "confidence": null}, {"bbox": [337.92849, 666.40634, 381.42549, 675.40634], "page": 1, "text": "TAUNTON", "source": "pdfplumber", "confidence": null}, {"bbox": [383.92749000000003, 666.40634, 397.42749, 675.40634], "page": 1, "text": "MA", "source": "pdfplumber", "confidence": null}, {"bbox": [399.92949, 666.40634, 444.96548999999993, 675.40634], "page": 1, "text": "027802465", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 686.0958400000001, 80.93218999999999, 693.5958400000001], "page": 1, "text": "Contact:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 686.40634, 294.44949, 695.40634], "page": 1, "text": "6174194772", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 706.0958400000001, 66.77219, 713.5958400000001], "page": 1, "text": "Date", "source": "pdfplumber", "confidence": null}, {"bbox": [68.85719, 706.0958400000001, 75.93719, 713.5958400000001], "page": 1, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [78.02219, 706.0958400000001, 118.85969, 713.5958400000001], "page": 1, "text": "Admission:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 706.40634, 290.43549, 715.40634], "page": 1, "text": "08-07-2001", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 726.0958400000001, 66.77219, 733.5958400000001], "page": 1, "text": "Date", "source": "pdfplumber", "confidence": null}, {"bbox": [68.85719, 726.0958400000001, 75.93719, 733.5958400000001], "page": 1, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [78.02219, 726.0958400000001, 116.78219000000001, 733.5958400000001], "page": 1, "text": "Discharge:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 726.40634, 290.43549, 735.40634], "page": 1, "text": "09-07-2001", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 746.0958400000001, 68.43718999999999, 753.5958400000001], "page": 1, "text": "Total", "source": "pdfplumber", "confidence": null}, {"bbox": [70.52219, 746.0958400000001, 90.94469000000001, 753.5958400000001], "page": 1, "text": "Days:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 746.40634, 249.41349, 755.40634], "page": 1, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [251.91549, 746.40634, 272.41749, 755.40634], "page": 1, "text": "Days", "source": "pdfplumber", "confidence": null}, {"bbox": [274.91949, 746.40634, 309.92949, 755.40634], "page": 1, "text": "(General", "source": "pdfplumber", "confidence": null}, {"bbox": [312.43149, 746.40634, 336.92949000000004, 755.40634], "page": 1, "text": "Ward)", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 766.0958400000001, 69.26969, 773.5958400000001], "page": 1, "text": "Ward", "source": "pdfplumber", "confidence": null}, {"bbox": [71.35469, 766.0958400000001, 91.35719, 773.5958400000001], "page": 1, "text": "Type:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 766.40634, 276.42249, 775.40634], "page": 1, "text": "General", "source": "pdfplumber", "confidence": null}, {"bbox": [278.92449, 766.40634, 300.42549, 775.40634], "page": 1, "text": "Ward", "source": "pdfplumber", "confidence": null}]
3ef8828c-4eb6-49e7-b3aa-cd1a95c10351	62a283f3-8530-4aac-a8cd-96371e9cd1eb	2	Treating\nDoctor:\nDr.\nSha\nNori\nReg.\nNo.:\nMCI-24278\nPrimary\nDiagnosis:\nHistory\nof\ntubal\nligation\n(situation)\nICD-10\n/\nSNOMED:\n267020005\nType\nof\nAdmission:\nInpatient\nAssessment\nusing\nAlcohol\nUse\nDisorders\nIdentification\nTest\n-\nConsumption\nProcedure:\n(procedure)\nProcedure\nCode:\n763302001\n4.\nHOSPITAL\nEXPENSE\nBREAKDOWN\nSr.\nCategory\nDescription\nAmount\n(Rs.)\n1\nRoom\nCharges\nGeneral\nWard\n–\n1\nDays\n3,500\n2\nProcedure\nCharges\nAssessment\nusing\nAlcohol\nUse\nDisorders\nIdentification\nTest\n-\n43,140\n3\nConsultation\nSpecialist\n–\n3\nvisits\n3,000\n4\nPharmacy\nMedicines,\nIV\nfluids\n13,820\n5\nLaboratory\nBlood\ntests,\npanels\n2,665\n6\nNursing\nNursing\ncare\n–\n1\ndays\n800\n7\nConsumables\nSurgical\nconsumables,\nIV\nlines\n9,859\n8\nMiscellaneous\nAdmin,\nFood,\nTransport\n1,923\nTOTAL\nAMOUNT\nRs.\n78,700\nSum\nInsured\nRs.\n200,000\nAmount\nExceeding\nPolicy\nRs.\n0\nCLAIM\nAMOUNT\nREQUESTED\nRs.\n78,700\n5.\nRISK\nFACTORS\nRisk\nFactor\nDetails\nAge\n49\nyears\n—\nLow\nrisk\ncategory\nPrevious\nClaims\nNo\nprior\nclaims\n—\nFirst-time\nclaimant\nDiagnoses\n1\ncondition(s):\nHistory\nof\ntubal\nligation\n(situation)\nClaim\nvs\nSum\nInsured\nRs.\n78,700\n=\n39%\nof\nRs.\n200,000\nWard\nType\nGeneral\nWard\nAdmission\nType\nInpatient\n6.\nDECLARATION\nI\nhereby\ndeclare\nthat\nthe\ninformation\nfurnished\nabove\nis\ntrue\nand\ncorrect.\nThe\npatient\nMrs.\nJoie561\nVolkman526\nwas\nadmitted\nto\nMORTON\nHOSPITAL\nA\nSTEWARD\nFAMILY\nHOSPITAL\nINC.\non\n08-07-2001\nwith\nHistory\nof\ntubal\nligation\n(situation)\nand\nunderwent\nAssessment\nusing\nAlcohol\nUse\nDisorders\nIdentification\nTest\n-\nConsumption\n(procedure).\nAll\ncharges\nare\nwithin\nthe\nsum\ninsured.\nAll\nprocedures\nwere\nmedically\nnecessary.	99	2026-05-11 04:28:19.751+00	[{"bbox": [50.51969, 54.072200000000066, 80.10718999999999, 61.572200000000066], "page": 2, "text": "Treating", "source": "pdfplumber", "confidence": null}, {"bbox": [82.19219, 54.072200000000066, 108.85469, 61.572200000000066], "page": 2, "text": "Doctor:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 54.38270000000011, 256.40649, 63.38270000000011], "page": 2, "text": "Dr.", "source": "pdfplumber", "confidence": null}, {"bbox": [258.90849000000003, 54.38270000000011, 274.91949000000005, 63.38270000000011], "page": 2, "text": "Sha", "source": "pdfplumber", "confidence": null}, {"bbox": [277.42149, 54.38270000000011, 293.91849, 63.38270000000011], "page": 2, "text": "Nori", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 74.07220000000007, 66.77219, 81.57220000000007], "page": 2, "text": "Reg.", "source": "pdfplumber", "confidence": null}, {"bbox": [68.85719, 74.07220000000007, 83.43719, 81.57220000000007], "page": 2, "text": "No.:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 74.38270000000011, 288.92349, 83.38270000000011], "page": 2, "text": "MCI-24278", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 94.07220000000007, 78.44969, 101.57220000000007], "page": 2, "text": "Primary", "source": "pdfplumber", "confidence": null}, {"bbox": [80.53469, 94.07220000000007, 118.87468999999999, 101.57220000000007], "page": 2, "text": "Diagnosis:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 94.38270000000011, 272.40849000000003, 103.38270000000011], "page": 2, "text": "History", "source": "pdfplumber", "confidence": null}, {"bbox": [274.91049, 94.38270000000011, 282.41649, 103.38270000000011], "page": 2, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [284.91849, 94.38270000000011, 304.43049, 103.38270000000011], "page": 2, "text": "tubal", "source": "pdfplumber", "confidence": null}, {"bbox": [306.93249000000003, 94.38270000000011, 335.44449000000003, 103.38270000000011], "page": 2, "text": "ligation", "source": "pdfplumber", "confidence": null}, {"bbox": [337.94649000000004, 94.38270000000011, 377.4564900000001, 103.38270000000011], "page": 2, "text": "(situation)", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 114.07220000000007, 74.27219, 121.57220000000007], "page": 2, "text": "ICD-10", "source": "pdfplumber", "confidence": null}, {"bbox": [76.35719, 114.07220000000007, 78.44219, 121.57220000000007], "page": 2, "text": "/", "source": "pdfplumber", "confidence": null}, {"bbox": [80.52718999999999, 114.07220000000007, 115.94219, 121.57220000000007], "page": 2, "text": "SNOMED:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 114.38270000000011, 289.44549, 123.38270000000011], "page": 2, "text": "267020005", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 134.07220000000007, 68.02468999999999, 141.57220000000007], "page": 2, "text": "Type", "source": "pdfplumber", "confidence": null}, {"bbox": [70.10969, 134.07220000000007, 77.18969, 141.57220000000007], "page": 2, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [79.27468999999999, 134.07220000000007, 120.11219, 141.57220000000007], "page": 2, "text": "Admission:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 134.3827000000001, 278.93349, 143.3827000000001], "page": 2, "text": "Inpatient", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 154.3827000000001, 293.42349, 163.3827000000001], "page": 2, "text": "Assessment", "source": "pdfplumber", "confidence": null}, {"bbox": [295.92549, 154.3827000000001, 317.43549, 163.3827000000001], "page": 2, "text": "using", "source": "pdfplumber", "confidence": null}, {"bbox": [319.93749, 154.3827000000001, 349.44849000000005, 163.3827000000001], "page": 2, "text": "Alcohol", "source": "pdfplumber", "confidence": null}, {"bbox": [351.95049000000006, 154.3827000000001, 367.95249000000007, 163.3827000000001], "page": 2, "text": "Use", "source": "pdfplumber", "confidence": null}, {"bbox": [370.45449, 154.3827000000001, 408.95649000000003, 163.3827000000001], "page": 2, "text": "Disorders", "source": "pdfplumber", "confidence": null}, {"bbox": [411.45849000000004, 154.3827000000001, 461.98449000000005, 163.3827000000001], "page": 2, "text": "Identification", "source": "pdfplumber", "confidence": null}, {"bbox": [464.48649, 154.3827000000001, 481.99149, 163.3827000000001], "page": 2, "text": "Test", "source": "pdfplumber", "confidence": null}, {"bbox": [484.49349, 154.3827000000001, 487.49049, 163.3827000000001], "page": 2, "text": "-", "source": "pdfplumber", "confidence": null}, {"bbox": [489.99249000000003, 154.3827000000001, 543.0114900000002, 163.3827000000001], "page": 2, "text": "Consumption", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 166.07220000000007, 90.11219, 173.57220000000007], "page": 2, "text": "Procedure:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 166.3827000000001, 290.92149, 175.3827000000001], "page": 2, "text": "(procedure)", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 186.07220000000007, 87.61469, 193.57220000000007], "page": 2, "text": "Procedure", "source": "pdfplumber", "confidence": null}, {"bbox": [89.69969, 186.07220000000007, 110.94718999999999, 193.57220000000007], "page": 2, "text": "Code:", "source": "pdfplumber", "confidence": null}, {"bbox": [244.40949, 186.3827000000001, 289.44549, 195.3827000000001], "page": 2, "text": "763302001", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 218.51429999999993, 57.191689999999994, 226.51429999999993], "page": 2, "text": "4.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 218.51429999999993, 99.86369, 226.51429999999993], "page": 2, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [102.08769, 218.51429999999993, 139.87968999999998, 226.51429999999993], "page": 2, "text": "EXPENSE", "source": "pdfplumber", "confidence": null}, {"bbox": [142.10368999999997, 218.51429999999993, 195.87168999999997, 226.51429999999993], "page": 2, "text": "BREAKDOWN", "source": "pdfplumber", "confidence": null}, {"bbox": [54.025064, 239.4108, 64.030064, 246.9108], "page": 2, "text": "Sr.", "source": "pdfplumber", "confidence": null}, {"bbox": [123.56246999999999, 239.4108, 156.06747, 246.9108], "page": 2, "text": "Category", "source": "pdfplumber", "confidence": null}, {"bbox": [314.77679, 239.4108, 356.03429, 246.9108], "page": 2, "text": "Description", "source": "pdfplumber", "confidence": null}, {"bbox": [486.19753, 239.4108, 514.5250299999999, 246.9108], "page": 2, "text": "Amount", "source": "pdfplumber", "confidence": null}, {"bbox": [516.6100299999999, 239.4108, 533.2750299999999, 246.9108], "page": 2, "text": "(Rs.)", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 259.51429999999993, 51.96769, 267.51429999999993], "page": 2, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 259.51429999999993, 102.87143999999999, 267.51429999999993], "page": 2, "text": "Room", "source": "pdfplumber", "confidence": null}, {"bbox": [105.09544, 259.51429999999993, 135.32744, 267.51429999999993], "page": 2, "text": "Charges", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 259.51429999999993, 237.55049000000002, 267.51429999999993], "page": 2, "text": "General", "source": "pdfplumber", "confidence": null}, {"bbox": [239.77449000000001, 259.51429999999993, 258.88649, 267.51429999999993], "page": 2, "text": "Ward", "source": "pdfplumber", "confidence": null}, {"bbox": [261.11049, 259.51429999999993, 265.55849, 267.51429999999993], "page": 2, "text": "–", "source": "pdfplumber", "confidence": null}, {"bbox": [267.78249, 259.51429999999993, 272.23049, 267.51429999999993], "page": 2, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [274.45449, 259.51429999999993, 292.67849, 267.51429999999993], "page": 2, "text": "Days", "source": "pdfplumber", "confidence": null}, {"bbox": [526.73996, 259.51429999999993, 546.75596, 267.51429999999993], "page": 2, "text": "3,500", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 279.51429999999993, 51.96769, 287.51429999999993], "page": 2, "text": "2", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 279.51429999999993, 118.43943999999999, 287.51429999999993], "page": 2, "text": "Procedure", "source": "pdfplumber", "confidence": null}, {"bbox": [120.66344, 279.51429999999993, 150.89544, 287.51429999999993], "page": 2, "text": "Charges", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 279.51429999999993, 252.66249, 287.51429999999993], "page": 2, "text": "Assessment", "source": "pdfplumber", "confidence": null}, {"bbox": [254.88649, 279.51429999999993, 274.00649, 287.51429999999993], "page": 2, "text": "using", "source": "pdfplumber", "confidence": null}, {"bbox": [276.23049000000003, 279.51429999999993, 302.46249000000006, 287.51429999999993], "page": 2, "text": "Alcohol", "source": "pdfplumber", "confidence": null}, {"bbox": [304.68649000000005, 279.51429999999993, 318.91049, 287.51429999999993], "page": 2, "text": "Use", "source": "pdfplumber", "confidence": null}, {"bbox": [321.13449, 279.51429999999993, 355.35848999999996, 287.51429999999993], "page": 2, "text": "Disorders", "source": "pdfplumber", "confidence": null}, {"bbox": [357.58249, 279.51429999999993, 402.49449, 287.51429999999993], "page": 2, "text": "Identification", "source": "pdfplumber", "confidence": null}, {"bbox": [404.71849, 279.51429999999993, 420.27849, 287.51429999999993], "page": 2, "text": "Test", "source": "pdfplumber", "confidence": null}, {"bbox": [422.50248999999997, 279.51429999999993, 425.16648999999995, 287.51429999999993], "page": 2, "text": "-", "source": "pdfplumber", "confidence": null}, {"bbox": [522.29196, 279.51429999999993, 546.75596, 287.51429999999993], "page": 2, "text": "43,140", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 299.51429999999993, 51.96769, 307.51429999999993], "page": 2, "text": "3", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 299.51429999999993, 125.99943999999999, 307.51429999999993], "page": 2, "text": "Consultation", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 299.51429999999993, 243.32648999999998, 307.51429999999993], "page": 2, "text": "Specialist", "source": "pdfplumber", "confidence": null}, {"bbox": [245.55049000000002, 299.51429999999993, 249.99849000000003, 307.51429999999993], "page": 2, "text": "–", "source": "pdfplumber", "confidence": null}, {"bbox": [252.22249, 299.51429999999993, 256.67049, 307.51429999999993], "page": 2, "text": "3", "source": "pdfplumber", "confidence": null}, {"bbox": [258.89449, 299.51429999999993, 276.67049000000003, 307.51429999999993], "page": 2, "text": "visits", "source": "pdfplumber", "confidence": null}, {"bbox": [526.73996, 299.51429999999993, 546.75596, 307.51429999999993], "page": 2, "text": "3,000", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 319.51429999999993, 51.96769, 327.51429999999993], "page": 2, "text": "4", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 319.51429999999993, 117.54344, 327.51429999999993], "page": 2, "text": "Pharmacy", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 319.51429999999993, 247.32649, 327.51429999999993], "page": 2, "text": "Medicines,", "source": "pdfplumber", "confidence": null}, {"bbox": [249.55049000000002, 319.51429999999993, 257.11049, 327.51429999999993], "page": 2, "text": "IV", "source": "pdfplumber", "confidence": null}, {"bbox": [259.33449, 319.51429999999993, 278.00649000000004, 327.51429999999993], "page": 2, "text": "fluids", "source": "pdfplumber", "confidence": null}, {"bbox": [522.29196, 319.51429999999993, 546.75596, 327.51429999999993], "page": 2, "text": "13,820", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 339.51430000000005, 51.96769, 347.51430000000005], "page": 2, "text": "5", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 339.51430000000005, 119.77544, 347.51430000000005], "page": 2, "text": "Laboratory", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 339.51430000000005, 229.55049000000002, 347.51430000000005], "page": 2, "text": "Blood", "source": "pdfplumber", "confidence": null}, {"bbox": [231.77449000000001, 339.51430000000005, 250.89449000000002, 347.51430000000005], "page": 2, "text": "tests,", "source": "pdfplumber", "confidence": null}, {"bbox": [253.11849, 339.51430000000005, 276.68649000000005, 347.51430000000005], "page": 2, "text": "panels", "source": "pdfplumber", "confidence": null}, {"bbox": [526.73996, 339.51430000000005, 546.75596, 347.51430000000005], "page": 2, "text": "2,665", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 359.51430000000005, 51.96769, 367.51430000000005], "page": 2, "text": "6", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 359.51430000000005, 109.09544, 367.51430000000005], "page": 2, "text": "Nursing", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 359.51430000000005, 236.65449, 367.51430000000005], "page": 2, "text": "Nursing", "source": "pdfplumber", "confidence": null}, {"bbox": [238.87849, 359.51430000000005, 254.43849000000003, 367.51430000000005], "page": 2, "text": "care", "source": "pdfplumber", "confidence": null}, {"bbox": [256.66249, 359.51430000000005, 261.11048999999997, 367.51430000000005], "page": 2, "text": "–", "source": "pdfplumber", "confidence": null}, {"bbox": [263.33449, 359.51430000000005, 267.78249, 367.51430000000005], "page": 2, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [270.00649, 359.51430000000005, 286.90249, 367.51430000000005], "page": 2, "text": "days", "source": "pdfplumber", "confidence": null}, {"bbox": [533.41196, 359.51430000000005, 546.75596, 367.51430000000005], "page": 2, "text": "800", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 379.51430000000005, 51.96769, 387.51430000000005], "page": 2, "text": "7", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 379.51430000000005, 130.43944, 387.51430000000005], "page": 2, "text": "Consumables", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 379.51430000000005, 237.99049000000002, 387.51430000000005], "page": 2, "text": "Surgical", "source": "pdfplumber", "confidence": null}, {"bbox": [240.21449, 379.51430000000005, 289.56649, 387.51430000000005], "page": 2, "text": "consumables,", "source": "pdfplumber", "confidence": null}, {"bbox": [291.79049, 379.51430000000005, 299.35049000000004, 387.51430000000005], "page": 2, "text": "IV", "source": "pdfplumber", "confidence": null}, {"bbox": [301.57449, 379.51430000000005, 318.02249, 387.51430000000005], "page": 2, "text": "lines", "source": "pdfplumber", "confidence": null}, {"bbox": [526.73996, 379.51430000000005, 546.75596, 387.51430000000005], "page": 2, "text": "9,859", "source": "pdfplumber", "confidence": null}, {"bbox": [47.51969, 399.51430000000005, 51.96769, 407.51430000000005], "page": 2, "text": "8", "source": "pdfplumber", "confidence": null}, {"bbox": [81.53544, 399.51430000000005, 132.21544, 407.51430000000005], "page": 2, "text": "Miscellaneous", "source": "pdfplumber", "confidence": null}, {"bbox": [209.09449, 399.51430000000005, 233.99049, 407.51430000000005], "page": 2, "text": "Admin,", "source": "pdfplumber", "confidence": null}, {"bbox": [236.21449, 399.51430000000005, 256.67049000000003, 407.51430000000005], "page": 2, "text": "Food,", "source": "pdfplumber", "confidence": null}, {"bbox": [258.89449, 399.51430000000005, 293.12649000000005, 407.51430000000005], "page": 2, "text": "Transport", "source": "pdfplumber", "confidence": null}, {"bbox": [526.73996, 399.51430000000005, 546.75596, 407.51430000000005], "page": 2, "text": "1,923", "source": "pdfplumber", "confidence": null}, {"bbox": [389.72549000000004, 425.39060000000006, 419.72249000000005, 434.39060000000006], "page": 2, "text": "TOTAL", "source": "pdfplumber", "confidence": null}, {"bbox": [422.22449000000006, 425.39060000000006, 461.71649, 434.39060000000006], "page": 2, "text": "AMOUNT", "source": "pdfplumber", "confidence": null}, {"bbox": [502.72796, 425.39060000000006, 516.73196, 434.39060000000006], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [519.23396, 425.39060000000006, 546.7559600000001, 434.39060000000006], "page": 2, "text": "78,700", "source": "pdfplumber", "confidence": null}, {"bbox": [407.20349, 445.39060000000006, 426.70649, 454.39060000000006], "page": 2, "text": "Sum", "source": "pdfplumber", "confidence": null}, {"bbox": [429.20849, 445.39060000000006, 461.71649, 454.39060000000006], "page": 2, "text": "Insured", "source": "pdfplumber", "confidence": null}, {"bbox": [497.72396, 445.39060000000006, 511.72796, 454.39060000000006], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [514.22996, 445.39060000000006, 546.75596, 454.39060000000006], "page": 2, "text": "200,000", "source": "pdfplumber", "confidence": null}, {"bbox": [351.18749, 465.39060000000006, 385.18049, 474.39060000000006], "page": 2, "text": "Amount", "source": "pdfplumber", "confidence": null}, {"bbox": [387.68249000000003, 465.39060000000006, 432.70049000000006, 474.39060000000006], "page": 2, "text": "Exceeding", "source": "pdfplumber", "confidence": null}, {"bbox": [435.20249, 465.39060000000006, 461.71649, 474.39060000000006], "page": 2, "text": "Policy", "source": "pdfplumber", "confidence": null}, {"bbox": [525.24596, 465.39060000000006, 539.2499599999999, 474.39060000000006], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [541.7519599999999, 465.39060000000006, 546.75596, 474.39060000000006], "page": 2, "text": "0", "source": "pdfplumber", "confidence": null}, {"bbox": [332.71949, 485.39060000000006, 361.21349000000004, 494.39060000000006], "page": 2, "text": "CLAIM", "source": "pdfplumber", "confidence": null}, {"bbox": [363.71549, 485.39060000000006, 403.20749, 494.39060000000006], "page": 2, "text": "AMOUNT", "source": "pdfplumber", "confidence": null}, {"bbox": [405.70948999999996, 485.39060000000006, 461.71648999999996, 494.39060000000006], "page": 2, "text": "REQUESTED", "source": "pdfplumber", "confidence": null}, {"bbox": [502.72796, 485.39060000000006, 516.73196, 494.39060000000006], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [519.23396, 485.39060000000006, 546.7559600000001, 494.39060000000006], "page": 2, "text": "78,700", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 517.5222000000001, 57.191689999999994, 525.5222000000001], "page": 2, "text": "5.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 517.5222000000001, 78.52768999999999, 525.5222000000001], "page": 2, "text": "RISK", "source": "pdfplumber", "confidence": null}, {"bbox": [80.75169, 517.5222000000001, 119.41568999999998, 525.5222000000001], "page": 2, "text": "FACTORS", "source": "pdfplumber", "confidence": null}, {"bbox": [107.13656, 538.4187000000001, 122.97656, 545.9187000000001], "page": 2, "text": "Risk", "source": "pdfplumber", "confidence": null}, {"bbox": [125.06156, 538.4187000000001, 147.98156, 545.9187000000001], "page": 2, "text": "Factor", "source": "pdfplumber", "confidence": null}, {"bbox": [370.38089, 538.4187000000001, 394.97339000000005, 545.9187000000001], "page": 2, "text": "Details", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 558.5222000000001, 62.751689999999996, 566.5222000000001], "page": 2, "text": "Age", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 558.5222000000001, 227.49439, 566.5222000000001], "page": 2, "text": "49", "source": "pdfplumber", "confidence": null}, {"bbox": [229.71839, 558.5222000000001, 249.27839, 566.5222000000001], "page": 2, "text": "years", "source": "pdfplumber", "confidence": null}, {"bbox": [251.50239, 558.5222000000001, 259.50239, 566.5222000000001], "page": 2, "text": "—", "source": "pdfplumber", "confidence": null}, {"bbox": [261.72639, 558.5222000000001, 276.39839, 566.5222000000001], "page": 2, "text": "Low", "source": "pdfplumber", "confidence": null}, {"bbox": [278.62239, 558.5222000000001, 291.06239, 566.5222000000001], "page": 2, "text": "risk", "source": "pdfplumber", "confidence": null}, {"bbox": [293.28639, 558.5222000000001, 323.96639, 566.5222000000001], "page": 2, "text": "category", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 578.5222000000001, 79.63969, 586.5222000000001], "page": 2, "text": "Previous", "source": "pdfplumber", "confidence": null}, {"bbox": [81.86368999999999, 578.5222000000001, 106.30369000000002, 586.5222000000001], "page": 2, "text": "Claims", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 578.5222000000001, 228.82239, 586.5222000000001], "page": 2, "text": "No", "source": "pdfplumber", "confidence": null}, {"bbox": [231.04639, 578.5222000000001, 247.04638999999997, 586.5222000000001], "page": 2, "text": "prior", "source": "pdfplumber", "confidence": null}, {"bbox": [249.27039, 578.5222000000001, 271.93439, 586.5222000000001], "page": 2, "text": "claims", "source": "pdfplumber", "confidence": null}, {"bbox": [274.15839, 578.5222000000001, 282.15839, 586.5222000000001], "page": 2, "text": "—", "source": "pdfplumber", "confidence": null}, {"bbox": [284.38239, 578.5222000000001, 317.71039, 586.5222000000001], "page": 2, "text": "First-time", "source": "pdfplumber", "confidence": null}, {"bbox": [319.93439, 578.5222000000001, 349.71839000000006, 586.5222000000001], "page": 2, "text": "claimant", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 598.5222000000001, 86.31169, 606.5222000000001], "page": 2, "text": "Diagnoses", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 598.5222000000001, 223.04639, 606.5222000000001], "page": 2, "text": "1", "source": "pdfplumber", "confidence": null}, {"bbox": [225.27039, 598.5222000000001, 268.83839, 606.5222000000001], "page": 2, "text": "condition(s):", "source": "pdfplumber", "confidence": null}, {"bbox": [271.06239, 598.5222000000001, 295.95039, 606.5222000000001], "page": 2, "text": "History", "source": "pdfplumber", "confidence": null}, {"bbox": [298.17439, 598.5222000000001, 304.84639, 606.5222000000001], "page": 2, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [307.07039000000003, 598.5222000000001, 324.4143900000001, 606.5222000000001], "page": 2, "text": "tubal", "source": "pdfplumber", "confidence": null}, {"bbox": [326.6383900000001, 598.5222000000001, 351.98239, 606.5222000000001], "page": 2, "text": "ligation", "source": "pdfplumber", "confidence": null}, {"bbox": [354.20639000000006, 598.5222000000001, 389.32639000000006, 606.5222000000001], "page": 2, "text": "(situation)", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 618.5222000000001, 68.95969, 626.5222000000001], "page": 2, "text": "Claim", "source": "pdfplumber", "confidence": null}, {"bbox": [71.18369, 618.5222000000001, 79.18369, 626.5222000000001], "page": 2, "text": "vs", "source": "pdfplumber", "confidence": null}, {"bbox": [81.40769, 618.5222000000001, 97.85569, 626.5222000000001], "page": 2, "text": "Sum", "source": "pdfplumber", "confidence": null}, {"bbox": [100.07969, 618.5222000000001, 126.75969, 626.5222000000001], "page": 2, "text": "Insured", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 618.5222000000001, 230.59839, 626.5222000000001], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [232.82238999999998, 618.5222000000001, 257.28639, 626.5222000000001], "page": 2, "text": "78,700", "source": "pdfplumber", "confidence": null}, {"bbox": [259.51039000000003, 618.5222000000001, 264.18239000000005, 626.5222000000001], "page": 2, "text": "=", "source": "pdfplumber", "confidence": null}, {"bbox": [266.40639, 618.5222000000001, 282.41439, 626.5222000000001], "page": 2, "text": "39%", "source": "pdfplumber", "confidence": null}, {"bbox": [284.63839, 618.5222000000001, 291.31039, 626.5222000000001], "page": 2, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [293.53439000000003, 618.5222000000001, 305.53439, 626.5222000000001], "page": 2, "text": "Rs.", "source": "pdfplumber", "confidence": null}, {"bbox": [307.75839, 618.5222000000001, 336.67039, 626.5222000000001], "page": 2, "text": "200,000", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 638.5222000000001, 67.63168999999999, 646.5222000000001], "page": 2, "text": "Ward", "source": "pdfplumber", "confidence": null}, {"bbox": [69.85569, 638.5222000000001, 87.63969, 646.5222000000001], "page": 2, "text": "Type", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 638.5222000000001, 247.05439, 646.5222000000001], "page": 2, "text": "General", "source": "pdfplumber", "confidence": null}, {"bbox": [249.27839, 638.5222000000001, 268.39038999999997, 646.5222000000001], "page": 2, "text": "Ward", "source": "pdfplumber", "confidence": null}, {"bbox": [48.51969, 658.5222000000001, 85.41569000000001, 666.5222000000001], "page": 2, "text": "Admission", "source": "pdfplumber", "confidence": null}, {"bbox": [87.63969, 658.5222000000001, 105.42369, 666.5222000000001], "page": 2, "text": "Type", "source": "pdfplumber", "confidence": null}, {"bbox": [218.59839, 658.5222000000001, 249.28638999999998, 666.5222000000001], "page": 2, "text": "Inpatient", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 690.8608, 57.191689999999994, 698.8608], "page": 2, "text": "6.", "source": "pdfplumber", "confidence": null}, {"bbox": [59.41569, 690.8608, 117.63168999999999, 698.8608], "page": 2, "text": "DECLARATION", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 713.86076, 52.74369, 721.86076], "page": 2, "text": "I", "source": "pdfplumber", "confidence": null}, {"bbox": [54.96769, 713.86076, 79.42369, 721.86076], "page": 2, "text": "hereby", "source": "pdfplumber", "confidence": null}, {"bbox": [81.64769, 713.86076, 107.87969000000001, 721.86076], "page": 2, "text": "declare", "source": "pdfplumber", "confidence": null}, {"bbox": [110.10369000000001, 713.86076, 123.44769000000004, 721.86076], "page": 2, "text": "that", "source": "pdfplumber", "confidence": null}, {"bbox": [125.67169000000004, 713.86076, 136.79169000000005, 721.86076], "page": 2, "text": "the", "source": "pdfplumber", "confidence": null}, {"bbox": [139.01569000000006, 713.86076, 178.58369000000008, 721.86076], "page": 2, "text": "information", "source": "pdfplumber", "confidence": null}, {"bbox": [180.80769000000006, 713.86076, 213.7116900000001, 721.86076], "page": 2, "text": "furnished", "source": "pdfplumber", "confidence": null}, {"bbox": [215.93569000000008, 713.86076, 237.7276900000001, 721.86076], "page": 2, "text": "above", "source": "pdfplumber", "confidence": null}, {"bbox": [239.9516900000001, 713.86076, 245.7276900000001, 721.86076], "page": 2, "text": "is", "source": "pdfplumber", "confidence": null}, {"bbox": [247.9516900000001, 713.86076, 261.7356900000001, 721.86076], "page": 2, "text": "true", "source": "pdfplumber", "confidence": null}, {"bbox": [263.9596900000001, 713.86076, 277.3036900000001, 721.86076], "page": 2, "text": "and", "source": "pdfplumber", "confidence": null}, {"bbox": [279.5276900000001, 713.86076, 306.1996900000001, 721.86076], "page": 2, "text": "correct.", "source": "pdfplumber", "confidence": null}, {"bbox": [308.4236900000001, 713.86076, 322.20768999999996, 721.86076], "page": 2, "text": "The", "source": "pdfplumber", "confidence": null}, {"bbox": [324.43169, 713.86076, 348.4476899999999, 721.86076], "page": 2, "text": "patient", "source": "pdfplumber", "confidence": null}, {"bbox": [350.6716899999999, 713.86076, 366.22368999999986, 721.86076], "page": 2, "text": "Mrs.", "source": "pdfplumber", "confidence": null}, {"bbox": [368.44768999999985, 713.86076, 396.4636899999997, 721.86076], "page": 2, "text": "Joie561", "source": "pdfplumber", "confidence": null}, {"bbox": [398.68768999999975, 713.86076, 443.1516899999996, 721.86076], "page": 2, "text": "Volkman526", "source": "pdfplumber", "confidence": null}, {"bbox": [445.3756899999996, 713.86076, 459.59968999999955, 721.86076], "page": 2, "text": "was", "source": "pdfplumber", "confidence": null}, {"bbox": [461.8236899999996, 713.86076, 492.50368999999944, 721.86076], "page": 2, "text": "admitted", "source": "pdfplumber", "confidence": null}, {"bbox": [494.7276899999995, 713.86076, 501.3996899999994, 721.86076], "page": 2, "text": "to", "source": "pdfplumber", "confidence": null}, {"bbox": [503.62368999999944, 713.86076, 539.1756899999993, 721.86076], "page": 2, "text": "MORTON", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 725.86076, 90.08769000000001, 733.86076], "page": 2, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [92.31169, 725.86076, 97.64769, 733.86076], "page": 2, "text": "A", "source": "pdfplumber", "confidence": null}, {"bbox": [99.87169, 725.86076, 139.87169, 733.86076], "page": 2, "text": "STEWARD", "source": "pdfplumber", "confidence": null}, {"bbox": [142.09569, 725.86076, 170.99169000000003, 733.86076], "page": 2, "text": "FAMILY", "source": "pdfplumber", "confidence": null}, {"bbox": [173.21569000000002, 725.86076, 212.78369000000006, 733.86076], "page": 2, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [215.00769000000005, 725.86076, 231.00769000000005, 733.86076], "page": 2, "text": "INC.", "source": "pdfplumber", "confidence": null}, {"bbox": [233.23169000000004, 725.86076, 242.12769000000006, 733.86076], "page": 2, "text": "on", "source": "pdfplumber", "confidence": null}, {"bbox": [244.35169000000005, 725.86076, 285.26369000000005, 733.86076], "page": 2, "text": "08-07-2001", "source": "pdfplumber", "confidence": null}, {"bbox": [287.48769000000004, 725.86076, 301.7116900000001, 733.86076], "page": 2, "text": "with", "source": "pdfplumber", "confidence": null}, {"bbox": [303.9356900000001, 725.86076, 328.82369000000006, 733.86076], "page": 2, "text": "History", "source": "pdfplumber", "confidence": null}, {"bbox": [331.04769, 725.86076, 337.71968999999996, 733.86076], "page": 2, "text": "of", "source": "pdfplumber", "confidence": null}, {"bbox": [339.94368999999995, 725.86076, 357.28768999999994, 733.86076], "page": 2, "text": "tubal", "source": "pdfplumber", "confidence": null}, {"bbox": [359.51168999999993, 725.86076, 384.85568999999987, 733.86076], "page": 2, "text": "ligation", "source": "pdfplumber", "confidence": null}, {"bbox": [387.0796899999998, 725.86076, 422.1996899999997, 733.86076], "page": 2, "text": "(situation)", "source": "pdfplumber", "confidence": null}, {"bbox": [424.42368999999974, 725.86076, 437.7676899999997, 733.86076], "page": 2, "text": "and", "source": "pdfplumber", "confidence": null}, {"bbox": [439.9916899999996, 725.86076, 477.3436899999995, 733.86076], "page": 2, "text": "underwent", "source": "pdfplumber", "confidence": null}, {"bbox": [479.5676899999995, 725.86076, 523.1356899999995, 733.86076], "page": 2, "text": "Assessment", "source": "pdfplumber", "confidence": null}, {"bbox": [525.3596899999994, 725.86076, 544.4796899999993, 733.86076], "page": 2, "text": "using", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 737.86076, 76.75169, 745.86076], "page": 2, "text": "Alcohol", "source": "pdfplumber", "confidence": null}, {"bbox": [78.97569, 737.86076, 93.19969, 745.86076], "page": 2, "text": "Use", "source": "pdfplumber", "confidence": null}, {"bbox": [95.42369, 737.86076, 129.64769, 745.86076], "page": 2, "text": "Disorders", "source": "pdfplumber", "confidence": null}, {"bbox": [131.87169, 737.86076, 176.78369000000004, 745.86076], "page": 2, "text": "Identification", "source": "pdfplumber", "confidence": null}, {"bbox": [179.00769000000003, 737.86076, 194.56769000000003, 745.86076], "page": 2, "text": "Test", "source": "pdfplumber", "confidence": null}, {"bbox": [196.79169000000002, 737.86076, 199.45569, 745.86076], "page": 2, "text": "-", "source": "pdfplumber", "confidence": null}, {"bbox": [201.67969, 737.86076, 248.80769000000004, 745.86076], "page": 2, "text": "Consumption", "source": "pdfplumber", "confidence": null}, {"bbox": [251.03169000000003, 737.86076, 294.59969, 745.86076], "page": 2, "text": "(procedure).", "source": "pdfplumber", "confidence": null}, {"bbox": [296.82369, 737.86076, 305.71169000000003, 745.86076], "page": 2, "text": "All", "source": "pdfplumber", "confidence": null}, {"bbox": [307.93569, 737.86076, 336.3916899999999, 745.86076], "page": 2, "text": "charges", "source": "pdfplumber", "confidence": null}, {"bbox": [338.61569, 737.86076, 350.1756899999999, 745.86076], "page": 2, "text": "are", "source": "pdfplumber", "confidence": null}, {"bbox": [352.39968999999985, 737.86076, 372.84768999999983, 745.86076], "page": 2, "text": "within", "source": "pdfplumber", "confidence": null}, {"bbox": [375.0716899999999, 737.86076, 386.19168999999977, 745.86076], "page": 2, "text": "the", "source": "pdfplumber", "confidence": null}, {"bbox": [388.4156899999998, 737.86076, 403.5276899999998, 745.86076], "page": 2, "text": "sum", "source": "pdfplumber", "confidence": null}, {"bbox": [405.7516899999997, 737.86076, 434.2076899999997, 745.86076], "page": 2, "text": "insured.", "source": "pdfplumber", "confidence": null}, {"bbox": [436.43168999999966, 737.86076, 445.31968999999964, 745.86076], "page": 2, "text": "All", "source": "pdfplumber", "confidence": null}, {"bbox": [447.54368999999963, 737.86076, 487.5596899999995, 745.86076], "page": 2, "text": "procedures", "source": "pdfplumber", "confidence": null}, {"bbox": [489.7836899999995, 737.86076, 507.1196899999994, 745.86076], "page": 2, "text": "were", "source": "pdfplumber", "confidence": null}, {"bbox": [509.34368999999947, 737.86076, 542.6796899999994, 745.86076], "page": 2, "text": "medically", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 749.86076, 89.19969, 757.86076], "page": 2, "text": "necessary.", "source": "pdfplumber", "confidence": null}]
91d74eaf-5edb-4e07-bada-12df5df62f75	62a283f3-8530-4aac-a8cd-96371e9cd1eb	3	Patient\nSignature:\n_______________\nDoctor\nSignature:\n_______________\nName:\nMrs.\nJoie561\nVolkman526\nDr.\nSha\nNori\nDate:\n09-07-2001\nDate:\n09-07-2001\nMORTON\nHOSPITAL\nA\nSTEWARD\nFAMILY\nHOSPITAL\nINC.\n|\n88\nWASHINGTON\nST,\nTAUNTON\nMA\n027802465\n|\nTel:\n6174194772\n|\nClaim:\nCLM-2026-138175\n|\nTPA:\nVipul\nMedcorp\nTPA	99	2026-05-11 04:28:19.751+00	[{"bbox": [50.51969, 55.072200000000066, 75.52468999999999, 62.572200000000066], "page": 3, "text": "Patient", "source": "pdfplumber", "confidence": null}, {"bbox": [77.60969, 55.072200000000066, 114.69718999999998, 62.572200000000066], "page": 3, "text": "Signature:", "source": "pdfplumber", "confidence": null}, {"bbox": [116.78218999999997, 55.072200000000066, 179.33219, 62.572200000000066], "page": 3, "text": "_______________", "source": "pdfplumber", "confidence": null}, {"bbox": [305.63779, 55.072200000000066, 329.80279, 62.572200000000066], "page": 3, "text": "Doctor", "source": "pdfplumber", "confidence": null}, {"bbox": [331.88779, 55.072200000000066, 368.97529, 62.572200000000066], "page": 3, "text": "Signature:", "source": "pdfplumber", "confidence": null}, {"bbox": [371.06029, 55.072200000000066, 433.61029, 62.572200000000066], "page": 3, "text": "_______________", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 77.38270000000011, 77.02468999999999, 86.38270000000011], "page": 3, "text": "Name:", "source": "pdfplumber", "confidence": null}, {"bbox": [79.52669, 77.38270000000011, 97.02269, 86.38270000000011], "page": 3, "text": "Mrs.", "source": "pdfplumber", "confidence": null}, {"bbox": [99.52468999999999, 77.38270000000011, 131.04269, 86.38270000000011], "page": 3, "text": "Joie561", "source": "pdfplumber", "confidence": null}, {"bbox": [133.54469, 77.38270000000011, 183.56669000000002, 86.38270000000011], "page": 3, "text": "Volkman526", "source": "pdfplumber", "confidence": null}, {"bbox": [305.63779, 77.38270000000011, 317.63479, 86.38270000000011], "page": 3, "text": "Dr.", "source": "pdfplumber", "confidence": null}, {"bbox": [320.13679, 77.38270000000011, 336.14779000000004, 86.38270000000011], "page": 3, "text": "Sha", "source": "pdfplumber", "confidence": null}, {"bbox": [338.64979, 77.38270000000011, 355.14679, 86.38270000000011], "page": 3, "text": "Nori", "source": "pdfplumber", "confidence": null}, {"bbox": [50.51969, 99.38270000000011, 72.02968999999999, 108.38270000000011], "page": 3, "text": "Date:", "source": "pdfplumber", "confidence": null}, {"bbox": [74.53169, 99.38270000000011, 120.55769, 108.38270000000011], "page": 3, "text": "09-07-2001", "source": "pdfplumber", "confidence": null}, {"bbox": [305.63779, 99.38270000000011, 327.14779, 108.38270000000011], "page": 3, "text": "Date:", "source": "pdfplumber", "confidence": null}, {"bbox": [329.64979, 99.38270000000011, 375.67579, 108.38270000000011], "page": 3, "text": "09-07-2001", "source": "pdfplumber", "confidence": null}, {"bbox": [49.2498, 132.30729999999994, 80.3578, 139.30729999999994], "page": 3, "text": "MORTON", "source": "pdfplumber", "confidence": null}, {"bbox": [82.3038, 132.30729999999994, 116.92579999999998, 139.30729999999994], "page": 3, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [118.87179999999998, 132.30729999999994, 123.54079999999998, 139.30729999999994], "page": 3, "text": "A", "source": "pdfplumber", "confidence": null}, {"bbox": [125.48679999999999, 132.30729999999994, 160.4868, 139.30729999999994], "page": 3, "text": "STEWARD", "source": "pdfplumber", "confidence": null}, {"bbox": [162.4328, 132.30729999999994, 187.71679999999998, 139.30729999999994], "page": 3, "text": "FAMILY", "source": "pdfplumber", "confidence": null}, {"bbox": [189.66279999999998, 132.30729999999994, 224.2848, 139.30729999999994], "page": 3, "text": "HOSPITAL", "source": "pdfplumber", "confidence": null}, {"bbox": [226.2308, 132.30729999999994, 240.2308, 139.30729999999994], "page": 3, "text": "INC.", "source": "pdfplumber", "confidence": null}, {"bbox": [242.1768, 132.30729999999994, 243.99679999999998, 139.30729999999994], "page": 3, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [245.94279999999998, 132.30729999999994, 253.72679999999997, 139.30729999999994], "page": 3, "text": "88", "source": "pdfplumber", "confidence": null}, {"bbox": [255.67279999999997, 132.30729999999994, 303.89579999999995, 139.30729999999994], "page": 3, "text": "WASHINGTON", "source": "pdfplumber", "confidence": null}, {"bbox": [305.8418, 132.30729999999994, 316.7338, 139.30729999999994], "page": 3, "text": "ST,", "source": "pdfplumber", "confidence": null}, {"bbox": [318.6798, 132.30729999999994, 352.5107999999999, 139.30729999999994], "page": 3, "text": "TAUNTON", "source": "pdfplumber", "confidence": null}, {"bbox": [354.45679999999993, 132.30729999999994, 364.95679999999993, 139.30729999999994], "page": 3, "text": "MA", "source": "pdfplumber", "confidence": null}, {"bbox": [366.90279999999996, 132.30729999999994, 401.9307999999999, 139.30729999999994], "page": 3, "text": "027802465", "source": "pdfplumber", "confidence": null}, {"bbox": [403.87679999999995, 132.30729999999994, 405.69679999999994, 139.30729999999994], "page": 3, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [407.64279999999997, 132.30729999999994, 419.31179999999995, 139.30729999999994], "page": 3, "text": "Tel:", "source": "pdfplumber", "confidence": null}, {"bbox": [421.2578, 132.30729999999994, 460.17779999999993, 139.30729999999994], "page": 3, "text": "6174194772", "source": "pdfplumber", "confidence": null}, {"bbox": [462.12379999999996, 132.30729999999994, 463.94379999999995, 139.30729999999994], "page": 3, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [465.8898, 132.30729999999994, 485.72079999999994, 139.30729999999994], "page": 3, "text": "Claim:", "source": "pdfplumber", "confidence": null}, {"bbox": [487.66679999999997, 132.30729999999994, 546.0258, 139.30729999999994], "page": 3, "text": "CLM-2026-138175", "source": "pdfplumber", "confidence": null}, {"bbox": [256.8523, 144.30729999999994, 258.6723, 151.30729999999994], "page": 3, "text": "|", "source": "pdfplumber", "confidence": null}, {"bbox": [260.61830000000003, 144.30729999999994, 276.1793, 151.30729999999994], "page": 3, "text": "TPA:", "source": "pdfplumber", "confidence": null}, {"bbox": [278.12530000000004, 144.30729999999994, 293.68629999999996, 151.30729999999994], "page": 3, "text": "Vipul", "source": "pdfplumber", "confidence": null}, {"bbox": [295.6323, 144.30729999999994, 322.8623, 151.30729999999994], "page": 3, "text": "Medcorp", "source": "pdfplumber", "confidence": null}, {"bbox": [324.80830000000003, 144.30729999999994, 338.42330000000004, 151.30729999999994], "page": 3, "text": "TPA", "source": "pdfplumber", "confidence": null}]
4d9cb7d4-d42e-41f0-b1da-529266b626cd	f248abf7-7f79-4b19-860c-dbf82a30a46a	1	MEDICAL INSURANCE CLAIM FORM\nNEVILLE CENTER AT FRESH POND FOR NURSING & REHAB | Claim Ref: CLM-2026-157424 | EMERGENCY\nRISK CLASSIFICATION: LOW RISK Routine admission | 1 diagnosis | 0 prior claim(s) | 35% of sum insured\n1. PATIENT INFORMATION\nPatient Name: Ms. Elfreda431 Beahan375\nDate of Birth: 07-11-1966\nGender: Female\nAge: 59 Years\nAddress: 600 Zieme Vista Unit 57, Malden, Massachusetts 02148\nPhone: +1-557-565-1946\nEmail: elfreda431.beahan375@gmail.com\nBlood Group: AB-\n2. INSURANCE INFORMATION\nInsurance Provider: Humana\nPolicy Number: POL-UI-2025-675898\nMember ID: MEM-27584297\nGroup Number: GRP-2025-224\nPolicy Type: Individual\nSum Insured: Rs. 500,000\nPolicy Start Date: 01-01-2025\nPolicy End Date: 31-12-2025\nPrevious Claims: None\nTotal Claimed: Rs. 0\nTPA: MD India Health Insurance TPA\n3. HOSPITALIZATION DETAILS\nHospital Name: NEVILLE CENTER AT FRESH POND FOR NURSING & REHAB\nRegistration: NEVI-REG-1472\nAddress: 640 CONCORD AVENUE, CAMBRIDGE MA 021381116\nContact: 6174970600\nDate of Admission: 20-10-2020\nDate of Discharge: 20-10-2020\nTotal Days: 1 Days (General Ward)\nWard Type: General Ward\n\nMEDICAL INSURANCE CLAIM FORM\nNEVILLE CENTER AT FRESH POND FOR NURSING & REHAB | Claim Ref: CLM-2026-157424 | EMERGENCY\n\n1. PATIENT INFORMATION | \nPatient Name: | Ms. Elfreda431 Beahan375\nDate of Birth: | 07-11-1966\nGender: | Female\nAge: | 59 Years\nAddress: | 600 Zieme Vista Unit 57, Malden, Massachusetts 02148\nPhone: | +1-557-565-1946\nEmail: | elfreda431.beahan375@gmail.com\nBlood Group: | AB-\n\n2. INSURANCE INFORMATION | \nInsurance Provider: | Humana\nPolicy Number: | POL-UI-2025-675898\nMember ID: | MEM-27584297\nGroup Number: | GRP-2025-224\nPolicy Type: | Individual\nSum Insured: | Rs. 500,000\nPolicy Start Date: | 01-01-2025\nPolicy End Date: | 31-12-2025\nPrevious Claims: | None\nTotal Claimed: | Rs. 0\nTPA: | MD India Health Insurance TPA\n\n3. HOSPITALIZATION DETAILS | \nHospital Name: | NEVILLE CENTER AT FRESH POND FOR NURSING & REHAB\nRegistration: | NEVI-REG-1472\nAddress: | 640 CONCORD AVENUE, CAMBRIDGE MA 021381116\nContact: | 6174970600\nDate of Admission: | 20-10-2020\nDate of Discharge: | 20-10-2020\nTotal Days: | 1 Days (General Ward)\nWard Type: | General Ward	99	2026-05-11 04:57:15.666141+00	\N
df56b6bf-c337-4913-88d8-05fd03924f9b	f248abf7-7f79-4b19-860c-dbf82a30a46a	2	Treating Doctor: Dr. Varty Chander\nReg. No.: MCI-83532\nPrimary Diagnosis: Fracture of mandible (disorder)\nICD-10 / SNOMED: 263172003\nType of Admission: Emergency\nProcedure: Plain X-ray of mandible (procedure)\nProcedure Code: 1290789000\n4. HOSPITAL EXPENSE BREAKDOWN\nSr. Category Description Amount (Rs.)\n1 Room Charges General Ward – 1 Days 8,000\n2 Procedure Charges Plain X-ray of mandible (procedure) 129,420\n3 Consultation Specialist – 3 visits 2,400\n4 Pharmacy Acetaminophen 325 MG / oxyCODO, Naproxen sodium 220 MG Or... 14,639\n5 Laboratory Blood tests, panels 3,536\n6 Nursing Nursing care – 1 days 1,200\n7 Consumables Surgical consumables, IV lines 13,854\n8 Miscellaneous Admin, Food, Transport 4,583\nTOTAL AMOUNT Rs. 177,600\nSum Insured Rs. 500,000\nAmount Exceeding Policy Rs. 0\nCLAIM AMOUNT REQUESTED Rs. 177,600\n5. RISK FACTORS\nRisk Factor Details\nAge 59 years — Low risk category\nPrevious Claims No prior claims — First-time claimant\nDiagnoses 1 condition(s): Fracture of mandible (disorder)\nClaim vs Sum Insured Rs. 177,600 = 35% of Rs. 500,000\nWard Type General Ward\nAdmission Type Emergency\n6. DECLARATION\nI hereby declare that the information furnished above is true and correct. The patient Ms. Elfreda431 Beahan375 was admitted to NEVILLE\nCENTER AT FRESH POND FOR NURSING & REHAB on 20-10-2020 with Fracture of mandible (disorder) and underwent Plain X-ray of\nmandible (procedure). All charges are within the sum insured. All procedures were medically necessary.\nPatient Signature: _______________ Doctor Signature: _______________\n\nTreating Doctor: | Dr. Varty Chander\nReg. No.: | MCI-83532\nPrimary Diagnosis: | Fracture of mandible (disorder)\nICD-10 / SNOMED: | 263172003\nType of Admission: | Emergency\nProcedure: | Plain X-ray of mandible (procedure)\nProcedure Code: | 1290789000\n\n4. HOSPITAL EXPENSE BREAKDOWN |  |  | \nSr. | Category | Description | Amount (Rs.)\n1 | Room Charges | General Ward – 1 Days | 8,000\n2 | Procedure Charges | Plain X-ray of mandible (procedure) | 129,420\n3 | Consultation | Specialist – 3 visits | 2,400\n4 | Pharmacy | Acetaminophen 325 MG / oxyCODO, Naproxen sodium 220 MG Or... | 14,639\n5 | Laboratory | Blood tests, panels | 3,536\n6 | Nursing | Nursing care – 1 days | 1,200\n7 | Consumables | Surgical consumables, IV lines | 13,854\n8 | Miscellaneous | Admin, Food, Transport | 4,583\n\n |  | TOTAL AMOUNT | Rs. 177,600\n |  | Sum Insured | Rs. 500,000\n |  | Amount Exceeding Policy | Rs. 0\n |  | CLAIM AMOUNT REQUESTED | Rs. 177,600\n\n5. RISK FACTORS | \nRisk Factor | Details\nAge | 59 years — Low risk category\nPrevious Claims | No prior claims — First-time claimant\nDiagnoses | 1 condition(s): Fracture of mandible (disorder)\nClaim vs Sum Insured | Rs. 177,600 = 35% of Rs. 500,000\nWard Type | General Ward\nAdmission Type | Emergency\n\n6. DECLARATION\nI hereby declare that the information furnished above is true and correct. The patient Ms. Elfreda431 Beahan375 was admitted to NEVILLE\nCENTER AT FRESH POND FOR NURSING & REHAB on 20-10-2020 with Fracture of mandible (disorder) and underwent Plain X-ray of\nmandible (procedure). All charges are within the sum insured. All procedures were medically necessary.\n\nPatient Signature: _______________ | Doctor Signature: _______________	99	2026-05-11 04:57:15.666141+00	\N
6afa7fa9-12d0-4856-988f-055c2ad15503	f248abf7-7f79-4b19-860c-dbf82a30a46a	3	Name: Ms. Elfreda431 Beahan375 Dr. Varty Chander\nDate: 20-10-2020 Date: 20-10-2020\nNEVILLE CENTER AT FRESH POND FOR NURSING & REHAB | 640 CONCORD AVENUE, CAMBRIDGE MA 0213811 | Tel: 6174970600 | Claim:\nCLM-2026-157424 | TPA: MD India Health Insurance TPA\n\nName: Ms. Elfreda431 Beahan375 | Dr. Varty Chander\nDate: 20-10-2020 | Date: 20-10-2020	99	2026-05-11 04:57:15.666141+00	\N
40081f1c-3c9c-4502-947c-da36f76d005b	2fc2a78d-3682-481b-8c0b-207d1aff3c67	1	Hospital Bill Receipt India\nXYZ Hospital\n123 Health Street; Wellness City; India 110011\nPhone: +91 22 1234 5678\nEmail: billing@xyzhospital in\nPatient Information:\nName: John Doe Patient ID: 123456\nDate of Admission: 01-Jul-2024 Date of Discharge: 05-Jul-2024\nBilling Information:\nDescription\nQuantit\nUnit Price\nTotal Price\nRoom Charges\ndays\n73,OoOlda {12,000.0\nSurgery Charges\n{50,000.0 {50,000.0\nAnesthesia Charges\n{15,000.0 {15,000.0\nMedication Charges\nCopyright @ Sample Templates com	\N	2026-05-11 04:57:44.193839+00	\N
25da5d7b-9655-418f-831c-ed387b3bea5d	e7d1ff76-6929-4f78-a588-b39a121f3155	1	MEDICAL INSURANCE CLAIM FORM\nCAREWELL URGENT CARE CENTERS OF MA PC | Claim Ref: CLM-2026-141704 | ELECTIVE\nRISK CLASSIFICATION: LOW RISK Routine admission | 1 diagnosis | 0 prior claim(s) | 46% of sum insured\n1. PATIENT INFORMATION\nPatient Name: Ms. Doloris378 Sipes176\nDate of Birth: 13-02-1967\nGender: Female\nAge: 59 Years\nAddress: 619 Kshlerin Park, Shrewsbury, Massachusetts 00000\nPhone: +1-395-434-5407\nEmail: doloris378.sipes176@gmail.com\nBlood Group: B+\n2. INSURANCE INFORMATION\nInsurance Provider: Anthem\nPolicy Number: POL-NI-2025-344907\nMember ID: MEM-65133300\nGroup Number: GRP-2025-822\nPolicy Type: Individual\nSum Insured: Rs. 300,000\nPolicy Start Date: 01-01-2025\nPolicy End Date: 31-12-2025\nPrevious Claims: None\nTotal Claimed: Rs. 0\nTPA: Paramount Health Services\n3. HOSPITALIZATION DETAILS\nHospital Name: CAREWELL URGENT CARE CENTERS OF MA PC\nRegistration: CARE-REG-7246\nAddress: 484 RTE 134, WORCESTER MA 016071728\nContact: 5086947901\nDate of Admission: 02-09-2024\nDate of Discharge: 02-09-2024\nTotal Days: 1 Days (General Ward)\nWard Type: General Ward\n\nMEDICAL INSURANCE CLAIM FORM\nCAREWELL URGENT CARE CENTERS OF MA PC | Claim Ref: CLM-2026-141704 | ELECTIVE\n\n1. PATIENT INFORMATION | \nPatient Name: | Ms. Doloris378 Sipes176\nDate of Birth: | 13-02-1967\nGender: | Female\nAge: | 59 Years\nAddress: | 619 Kshlerin Park, Shrewsbury, Massachusetts 00000\nPhone: | +1-395-434-5407\nEmail: | doloris378.sipes176@gmail.com\nBlood Group: | B+\n\n2. INSURANCE INFORMATION | \nInsurance Provider: | Anthem\nPolicy Number: | POL-NI-2025-344907\nMember ID: | MEM-65133300\nGroup Number: | GRP-2025-822\nPolicy Type: | Individual\nSum Insured: | Rs. 300,000\nPolicy Start Date: | 01-01-2025\nPolicy End Date: | 31-12-2025\nPrevious Claims: | None\nTotal Claimed: | Rs. 0\nTPA: | Paramount Health Services\n\n3. HOSPITALIZATION DETAILS | \nHospital Name: | CAREWELL URGENT CARE CENTERS OF MA PC\nRegistration: | CARE-REG-7246\nAddress: | 484 RTE 134, WORCESTER MA 016071728\nContact: | 5086947901\nDate of Admission: | 02-09-2024\nDate of Discharge: | 02-09-2024\nTotal Days: | 1 Days (General Ward)\nWard Type: | General Ward	99	2026-05-11 05:00:30.258566+00	\N
41899942-5819-4346-8adc-995ce1739b35	e7d1ff76-6929-4f78-a588-b39a121f3155	2	Treating Doctor: Dr. Sandal Purohit\nReg. No.: MCI-81993\nPrimary Diagnosis: Medication review due (situation)\nICD-10 / SNOMED: 314529007\nType of Admission: Elective\nProcedure: Medication reconciliation (procedure)\nProcedure Code: 430193006\n4. HOSPITAL EXPENSE BREAKDOWN\nSr. Category Description Amount (Rs.)\n1 Room Charges General Ward – 1 Days 8,000\n2 Procedure Charges Medication reconciliation (procedure) 101,984\n3 Consultation Specialist – 3 visits 4,500\n4 Pharmacy lisinopril 10 MG Oral Tablet 73\n5 Laboratory Glucose [Mass/volume] in , Urea nitrogen [Mass/volum 3,309\n6 Nursing Nursing care – 1 days 1,000\n7 Consumables Surgical consumables, IV lines 16,920\n8 Miscellaneous Admin, Food, Transport 3,136\nTOTAL AMOUNT Rs. 138,900\nSum Insured Rs. 300,000\nAmount Exceeding Policy Rs. 0\nCLAIM AMOUNT REQUESTED Rs. 138,900\n5. RISK FACTORS\nRisk Factor Details\nAge 59 years — Low risk category\nPrevious Claims No prior claims — First-time claimant\nDiagnoses 1 condition(s): Medication review due (situation)\nClaim vs Sum Insured Rs. 138,900 = 46% of Rs. 300,000\nWard Type General Ward\nAdmission Type Elective\n6. DECLARATION\nI hereby declare that the information furnished above is true and correct. The patient Ms. Doloris378 Sipes176 was admitted to CAREWELL\nURGENT CARE CENTERS OF MA PC on 02-09-2024 with Medication review due (situation) and underwent Medication reconciliation\n(procedure). All charges are within the sum insured. All procedures were medically necessary.\nPatient Signature: _______________ Doctor Signature: _______________\n\nTreating Doctor: | Dr. Sandal Purohit\nReg. No.: | MCI-81993\nPrimary Diagnosis: | Medication review due (situation)\nICD-10 / SNOMED: | 314529007\nType of Admission: | Elective\nProcedure: | Medication reconciliation (procedure)\nProcedure Code: | 430193006\n\n4. HOSPITAL EXPENSE BREAKDOWN |  |  | \nSr. | Category | Description | Amount (Rs.)\n1 | Room Charges | General Ward – 1 Days | 8,000\n2 | Procedure Charges | Medication reconciliation (procedure) | 101,984\n3 | Consultation | Specialist – 3 visits | 4,500\n4 | Pharmacy | lisinopril 10 MG Oral Tablet | 73\n5 | Laboratory | Glucose [Mass/volume] in , Urea nitrogen [Mass/volum | 3,309\n6 | Nursing | Nursing care – 1 days | 1,000\n7 | Consumables | Surgical consumables, IV lines | 16,920\n8 | Miscellaneous | Admin, Food, Transport | 3,136\n\n |  | TOTAL AMOUNT | Rs. 138,900\n |  | Sum Insured | Rs. 300,000\n |  | Amount Exceeding Policy | Rs. 0\n |  | CLAIM AMOUNT REQUESTED | Rs. 138,900\n\n5. RISK FACTORS | \nRisk Factor | Details\nAge | 59 years — Low risk category\nPrevious Claims | No prior claims — First-time claimant\nDiagnoses | 1 condition(s): Medication review due (situation)\nClaim vs Sum Insured | Rs. 138,900 = 46% of Rs. 300,000\nWard Type | General Ward\nAdmission Type | Elective\n\n6. DECLARATION\nI hereby declare that the information furnished above is true and correct. The patient Ms. Doloris378 Sipes176 was admitted to CAREWELL\nURGENT CARE CENTERS OF MA PC on 02-09-2024 with Medication review due (situation) and underwent Medication reconciliation\n(procedure). All charges are within the sum insured. All procedures were medically necessary.\n\nPatient Signature: _______________ | Doctor Signature: _______________	99	2026-05-11 05:00:30.258566+00	\N
41599ce7-9547-4084-8011-95e477d5adec	e7d1ff76-6929-4f78-a588-b39a121f3155	3	Name: Ms. Doloris378 Sipes176 Dr. Sandal Purohit\nDate: 02-09-2024 Date: 02-09-2024\nCAREWELL URGENT CARE CENTERS OF MA PC | 484 RTE 134, WORCESTER MA 016071728 | Tel: 5086947901 | Claim: CLM-2026-141704 | TPA:\nParamount Health Services\n\nName: Ms. Doloris378 Sipes176 | Dr. Sandal Purohit\nDate: 02-09-2024 | Date: 02-09-2024	99	2026-05-11 05:00:30.258566+00	\N
\.


--
-- Data for Name: parse_jobs; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.parse_jobs (id, claim_id, status, total_documents, processed_documents, set_hash, model_version, used_fallback, error_message, created_at, completed_at) FROM stdin;
87f07bd6-bb0c-465a-8903-50690be23879	2955fa3a-1aa0-4437-b917-423f90841476	COMPLETED	1	1	b7a56c62ec75f07f0e625788a324b294c988c907375b8fc528147d06608644ed	dynamic_v2	f	\N	2026-05-11 04:28:21.673048+00	2026-05-11 04:28:22.160906+00
2b16defa-e308-4709-8429-83d3a989d83c	c5568d07-3434-4c94-b892-b963801e95d9	COMPLETED	1	1	976753ecab0e9e37d200de2d09b3ecd58d3e6a522765241503166071933d8eeb	heuristic-v2	t	\N	2026-05-11 04:57:17.14803+00	2026-05-11 04:57:21.958962+00
8697743d-7251-4039-a1f9-99a2c8b80c66	2ba4f78a-c552-47df-8372-3a62cde2e4d1	COMPLETED	1	1	f5b20355962bce1e62afb925a3f115ba81b2a7a37171e0501e0e6846dbea7b20	heuristic-v2	t	\N	2026-05-11 04:57:53.344152+00	2026-05-11 04:57:53.535512+00
7d684ebc-f365-4d54-9e7e-21fbdbb8eb41	647da5fa-9272-4ab8-81f0-b6b57a1886a3	COMPLETED	1	1	51ab25d5e029448426bcbf1292a6fa25aa7e24941696d1038f42cdf24e5554c5	heuristic-v2	t	\N	2026-05-11 05:01:17.155202+00	2026-05-11 05:01:21.492568+00
\.


--
-- Data for Name: parsed_fields; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.parsed_fields (id, claim_id, document_id, field_name, field_value, bounding_box, source_page, doc_type, model_version, created_at) FROM stdin;
fda44ff4-529f-4ac3-9131-8aa8a5a4a5e3	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	table_confidence	1.0	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
225c355c-e0fc-4333-8e66-164ee99ae1f2	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	reconciliation_status	mismatch	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
e947cd15-1425-468c-9127-d5ca32d22acb	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	parser_version	dynamic_v2	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
bcb8db01-450a-458e-a16f-ab2b5821d601	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	expense_pharmacy	13820.0	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
c1da457c-1d0f-4c60-a253-7438b5a2a67b	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	expense_laboratory	2665.0	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
589358d9-bba2-47e0-9cf4-2a3b7c8535e9	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	total_amount	9859.0	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
0b7d7018-2bc9-46f7-88e8-224ed5756e76	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	table_confidence	1.0	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
c8df5a8a-58a9-4434-84b6-ddf367dcfc02	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	reconciliation_status	missing_details	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
979a9697-a2de-4522-9f9f-6919781c101e	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	parser_version	dynamic_v2	null	2	UNKNOWN	dynamic_v2	2026-05-11 04:28:22.078288+00
44a762a0-c357-434e-9084-bbb87f99e376	2955fa3a-1aa0-4437-b917-423f90841476	\N	patient_name	Date: 09-07-2001	null	\N	\N	spatial_kv_v1	2026-05-11 04:28:22.078288+00
2ebf1039-3b1f-44a7-acab-97a685cfd2ee	2955fa3a-1aa0-4437-b917-423f90841476	\N	phone	Email: Blood 2. Insurance Policy Member Group Policy Sum Policy Policy Previous Total TPA: 3. Hospital	null	\N	\N	spatial_kv_v1	2026-05-11 04:28:22.078288+00
1d4d00b2-fbf7-4471-b41a-b0ec62d0e811	2955fa3a-1aa0-4437-b917-423f90841476	\N	doctor_name	Type Code: A Disorders STEWARD Insured EXPENSE Charges Risk that Charges Category Factor the Identification information FAMILY BREAKDOWN HOSPITAL Test furnished - Consumption General Assessment Specialist Medicines, Blood Nursing Surgical Admin, INC. above 49 No 1 Rs. General Inpatient condition(s): years prior tests, 78,700 on Food, care Ward is consumables, 08-07-2001	null	\N	\N	spatial_kv_v1	2026-05-11 04:28:22.078288+00
e40adcf6-83dd-457b-900e-c8a3853cdab6	2955fa3a-1aa0-4437-b917-423f90841476	\N	diagnosis	Ref: CLM-2026-138175 FORM MA FAMILY | 0 027802465 prior 02780 claim(s) HOSPITAL | | 39% INPATIENT of INC. sum insured	null	\N	\N	spatial_kv_v1	2026-05-11 04:28:22.078288+00
952d6a32-64be-4433-b908-457437eccf08	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	cpt_code	02780	null	1	UNKNOWN	paddleocr-vl-1.5-doc-parser	2026-05-11 04:28:22.078288+00
b904a63d-a687-47c4-a2f2-6892f9613369	2955fa3a-1aa0-4437-b917-423f90841476	62a283f3-8530-4aac-a8cd-96371e9cd1eb	cpt_code	24278	null	2	UNKNOWN	paddleocr-vl-1.5-doc-parser	2026-05-11 04:28:22.078288+00
6db86c60-9517-4822-83d4-9bec509fabd9	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	patient_name	Ms. Elfreda431 Beahan375	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
3995cb76-4c76-4245-839e-7075211a5fe6	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	date_of_birth	07-11-1966	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
767e1b1f-5b42-4b54-8379-3e43e6a88599	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	age	59	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
13375f91-b099-4bbf-a10b-5f696138dc94	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	gender	Female	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
a892d597-434f-4a8d-a114-456c060eeff9	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	address	600 Zieme Vista Unit 57, Malden, Massachusetts 02148	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
3228d5c8-53d3-4a9d-9500-3086839e96de	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	address	640 CONCORD AVENUE, CAMBRIDGE MA 021381116	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
6938740b-1b44-49e7-ac26-dbea54adba88	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	address	| 600 Zieme Vista Unit 57, Malden, Massachusetts 02148	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
f54c8dc1-2f37-4f5e-a1a3-2edd74a4eae6	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	address	| 640 CONCORD AVENUE, CAMBRIDGE MA 021381116	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
e502eb6f-d888-4f8a-8e31-fda568d6ccca	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	phone	+1-557-565-1946	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
5e5c8730-112c-463d-aae3-c3c966ff83c2	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	email	elfreda431.beahan375@gmail.com\nBlood	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
45125d41-fbbd-48d3-953d-1a2cf529d3fe	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	policy_number	POL-UI-2025-675898	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
77cc51ec-8374-47f6-abbb-fddfa2f73d02	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	claim_number	CLM-2026-157424	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
a10b6644-e558-4556-9e99-9102a6b08afc	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	member_id	MEM-27584297	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
9218e483-21ce-4482-9178-ca5b2df2f7f1	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	insurer	Humana	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
11ff8686-6914-4728-92d6-493eda8ee65f	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	hospital_name	NEVILLE CENTER AT FRESH POND FOR NURSING & REHAB	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
e537637f-6d4c-459d-a209-af7ee3b67eb6	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	admission_date	20-10-2020	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
8df26f70-235b-4293-b612-9cd1349ae6fa	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	discharge_date	20-10-2020	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
c2be2643-3b79-44c4-9e89-b06020bc17da	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	General Ward – 1 Days	8000.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
b1d4e551-4ae5-4e57-adea-433d8382fcbc	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Plain X-ray of mandible (procedure)	129420.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
fa573359-207f-4316-a25c-45e7aaf86bdd	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Specialist – 3 visits	2400.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
ed75bb39-6576-46bf-8374-585ef13d9dea	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Acetaminophen 325 MG / oxyCODO, Naproxen sodium 220 MG Or...	14639.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
01db82ba-c82f-4713-81b2-dad94e78a696	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Blood tests, panels	3536.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
3b46a50b-cbe2-4e30-8d40-9b6fb2fa37ea	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Nursing care – 1 days	1200.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
54cfd8bb-52f3-4a26-bce1-41d8dfa15e68	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Surgical consumables, IV lines	13854.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
7cc29f61-40f0-4f73-b183-1440a80d1b34	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	Admin, Food, Transport	4583.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 04:57:21.862643+00
f7b2f7ec-9dc0-4bb7-995f-a08bf8223278	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	diagnosis	Fracture of mandible (disorder)	null	2	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
e2566325-f03f-4bd4-ad4a-869c57364cfe	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	doctor_name	Varty Chander	null	2	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
b87c09c8-cd0f-4871-9f42-28df8ce92ead	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	phone	6174970600	null	3	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
faa50c82-76cd-4b06-bb30-80a88679ea57	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	insurer	Ms. Elfreda431 Beahan375	null	3	UNKNOWN	heuristic-v2	2026-05-11 04:57:21.862643+00
b2c41317-c4c0-46da-99e3-cd9502cea2b1	c5568d07-3434-4c94-b892-b963801e95d9	f248abf7-7f79-4b19-860c-dbf82a30a46a	cpt_code	02148	null	1	UNKNOWN	paddleocr-vl-1.5-doc-parser	2026-05-11 04:57:21.862643+00
deebe9bb-22a4-4085-804b-10a8966d85da	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	Room Charges	12000.00	null	1	UNKNOWN	expense-table-v5	2026-05-11 04:57:53.501191+00
74bef57e-946d-486c-9101-95e5fe674823	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	Surgery Charges	50000.00	null	1	UNKNOWN	expense-table-v5	2026-05-11 04:57:53.501191+00
181c0e6e-3230-48aa-9a21-95b25e1b0c26	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	Anesthesia Charges	15000.00	null	1	UNKNOWN	expense-table-v5	2026-05-11 04:57:53.501191+00
2d55bc5c-4f40-468e-bc3e-2a30618b9616	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	patient_name	John Doe	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
35402139-b1b6-42c7-b1f3-f8583718dd2f	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	phone	+91 22 1234 567	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
16bfff12-210a-4a6c-85ec-c0e1e08cb0e7	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	email	billing@xyzhospital in	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
391dd72f-761d-4fac-890a-5652ba99a756	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	patient_id	123456	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
45fcbb0a-67e5-4980-a642-00c6cf2bc515	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	admission_date	01-Jul-2024	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
a3999b83-0dcb-4e8f-bc24-83bd0916ca98	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	discharge_date	05-Jul-2024	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
5bdfa25b-ceb0-40c3-a48f-20f48ea307bf	2ba4f78a-c552-47df-8372-3a62cde2e4d1	2fc2a78d-3682-481b-8c0b-207d1aff3c67	hospital_name	XYZ Hospital	null	1	UNKNOWN	heuristic-v2	2026-05-11 04:57:53.501191+00
f10c0d61-c054-458f-89ec-4aa3979021d1	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	patient_name	Ms. Doloris378 Sipes176	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
064dbdb2-ef37-4f09-b24b-d36de1d0bc16	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	date_of_birth	13-02-1967	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
4097cbb6-892f-48e9-a14f-41a2f510d141	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	age	59	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
29cdecb9-15f3-40d6-a079-858b16d66341	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	gender	Female	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
4aa5c740-0b47-4bd6-8777-812b40eced80	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	address	619 Kshlerin Park, Shrewsbury, Massachusetts 00000	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
1c5e40c7-cd79-4327-9122-84aad67937a3	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	address	484 RTE 134, WORCESTER MA 016071728	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
83223e57-35b3-41ca-be74-6c9f545ba7e7	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	address	| 619 Kshlerin Park, Shrewsbury, Massachusetts 00000	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
4a01feee-3314-4649-a895-89641f334430	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	address	| 484 RTE 134, WORCESTER MA 016071728	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
a2ee5028-0b3f-436e-aa29-bea115821cb1	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	phone	+1-395-434-5407	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
eb18ed87-0ae7-45ca-9dd6-b255ecb29acd	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	email	doloris378.sipes176@gmail.com\nBlood	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
ac4d1144-c9f7-4b13-a1a6-7865bd6b5c73	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	policy_number	POL-NI-2025-344907	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
9cacf435-1719-460b-8e5b-0877e1cc07a6	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	claim_number	CLM-2026-141704	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
c9a01e80-b3fb-4506-8a68-5da33bc370a2	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	member_id	MEM-65133300	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
46761cb4-a8ea-47e8-91aa-a0adc061dcf8	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	insurer	Anthem	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
6045d8a0-bb46-4df2-aa99-731efe2fc8c6	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	hospital_name	CAREWELL URGENT CARE CENTERS OF MA PC	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
e837ddae-b119-40d7-9146-45bf2d92ecc8	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	admission_date	02-09-2024	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
0e6fed33-e361-4907-a20a-f3a28fff1f67	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	discharge_date	02-09-2024	null	1	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
32ff775a-fe3e-43e4-8f36-1696db27c569	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	General Ward – 1 Days	8000.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
38512d76-711a-4d48-81b2-9acd17796868	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Medication reconciliation (procedure)	101984.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
9be7a1e2-c433-40b6-a8ff-0bc4e341300b	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Specialist – 3 visits	4500.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
362c2623-c085-4d78-97d5-7451f48d489d	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	lisinopril 10 MG Oral Tablet	73.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
87a56197-8788-4b29-9f97-49d91f333c09	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Glucose [Mass/volume] in , Urea nitrogen [Mass/volum	3309.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
75e160af-5a5d-4363-bedf-5dcd4f1ba5bb	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Nursing care – 1 days	1000.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
82965523-80d7-4eb9-a823-28663bac51a3	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Surgical consumables, IV lines	16920.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
2ac7742d-687d-44e1-ac6e-c34cd950cb9b	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	Admin, Food, Transport	3136.00	null	2	UNKNOWN	expense-table-v5	2026-05-11 05:01:21.382869+00
c2c87b2e-4d57-47ff-a6da-3a3cf5549516	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	diagnosis	Medication review due (situation)	null	2	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
1000c28d-4c03-4173-ab49-e0a660b3c3e4	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	doctor_name	Sandal Purohit	null	2	UNKNOWN	heuristic-v2	2026-05-11 05:01:21.382869+00
6269a321-ae8d-4d01-9c33-baa06e7e3893	647da5fa-9272-4ab8-81f0-b6b57a1886a3	e7d1ff76-6929-4f78-a588-b39a121f3155	cpt_code	00000	null	1	UNKNOWN	paddleocr-vl-1.5-doc-parser	2026-05-11 05:01:21.382869+00
\.


--
-- Data for Name: predictions; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.predictions (id, claim_id, rejection_score, top_reasons, model_name, model_version, created_at) FROM stdin;
665481ad-155e-4477-8475-dda35430959c	2955fa3a-1aa0-4437-b917-423f90841476	0.19	[{"reason": "Missing policy number", "weight": 0.08}, {"reason": "Missing date of service / admission date", "weight": 0.08}, {"reason": "Two procedures performed", "weight": 0.03}]	heuristic	0.1.0	2026-05-11 04:28:22.61815+00
72b64099-4e09-41bc-936d-f43b06e5ace9	c5568d07-3434-4c94-b892-b963801e95d9	0.18	[{"reason": "Missing total amount (no charges found)", "weight": 0.1}, {"reason": "Multiple ICD codes (2)", "weight": 0.04}, {"reason": "Middle-aged patient (moderate risk band)", "weight": 0.04}]	heuristic	0.1.0	2026-05-11 04:57:22.534096+00
10babfb5-8a0f-455e-8c60-ef0a2fc36492	2ba4f78a-c552-47df-8372-3a62cde2e4d1	0.43	[{"reason": "Missing diagnosis", "weight": 0.12}, {"reason": "Missing total amount (no charges found)", "weight": 0.1}, {"reason": "Missing policy number", "weight": 0.08}, {"reason": "No ICD-10 codes found", "weight": 0.05}, {"reason": "Multi-day hospital stay (4 days)", "weight": 0.05}]	heuristic	0.1.0	2026-05-11 04:57:53.686983+00
bb5c030c-467c-4939-8f98-6abdea45b6cb	647da5fa-9272-4ab8-81f0-b6b57a1886a3	0.14	[{"reason": "Missing total amount (no charges found)", "weight": 0.1}, {"reason": "Middle-aged patient (moderate risk band)", "weight": 0.04}]	heuristic	0.1.0	2026-05-11 05:01:21.929558+00
\.


--
-- Data for Name: scan_analyses; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.scan_analyses (id, document_id, claim_id, scan_type, body_part, modality, findings, impression, recommendation, confidence, metadata, created_at) FROM stdin;
ab493829-69a6-42ae-a338-65d20b2d8dc1	f248abf7-7f79-4b19-860c-dbf82a30a46a	c5568d07-3434-4c94-b892-b963801e95d9	X-Ray	\N	\N	[{"finding": "Primary Diagnosis: Fracture of mandible (disorder). Diagnoses 1 condition(s): Fracture of mandible (disorder). CENTER AT FRESH POND FOR NURSING & REHAB on 20-10-2020 with Fracture of mandible (disorder) and underwent Plain X-ray of. Primary Diagnosis: | Fracture of mandible (disorder). Diagnoses | 1", "severity": "critical", "confidence": 0.85}]	Significant abnormalities detected: 1 critical finding(s). Clinical correlation advised.	\N	0.8500000000000001	\N	2026-05-11 04:57:15.666141+00
\.


--
-- Data for Name: submissions; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.submissions (id, claim_id, payer, request_payload, response_payload, status, submitted_at) FROM stdin;
\.


--
-- Data for Name: tpa_providers; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.tpa_providers (id, code, name, logo, provider_type, email, phone, website, address, is_active, created_at) FROM stdin;
b0c75733-f1a9-400e-958b-034b91cb4bed	icici_lombard	ICICI Lombard	🏦	Private	claims@icicilombard.com	1800-266-7700	https://www.icicilombard.com	\N	t	2026-05-11 04:21:08.59932+00
992370c9-9bdc-460f-b1d6-e65ec3a60634	star_health	Star Health	⭐	Private	claims@starhealth.in	1800-425-2255	https://www.starhealth.in	\N	t	2026-05-11 04:21:08.59932+00
9f186433-d6c1-40ac-8b36-b3b2e87760c8	hdfc_ergo	HDFC ERGO	🔷	Private	claims@hdfcergo.com	1800-266-0700	https://www.hdfcergo.com	\N	t	2026-05-11 04:21:08.59932+00
460d118f-7b21-412a-8aed-b1e865560ace	bajaj_allianz	Bajaj Allianz	🛡️	Private	claims@bajajallianz.co.in	1800-209-5858	https://www.bajajallianz.com	\N	t	2026-05-11 04:21:08.59932+00
4d75e2a9-62d6-4305-ab19-15c361449a9c	new_india	New India Assurance	🇮🇳	PSU	claims@newindia.co.in	1800-209-1415	https://www.newindia.co.in	\N	t	2026-05-11 04:21:08.59932+00
06118845-0a25-4d14-a634-74cbf6d7f964	niva_bupa	Niva Bupa	💙	Private	claims@nivabupa.com	1800-200-5577	https://www.nivabupa.com	\N	t	2026-05-11 04:21:08.59932+00
e5de5793-ff33-441d-8837-67d2089ba380	care_health	Care Health	💚	Private	claims@careinsurance.com	1800-102-4488	https://www.careinsurance.com	\N	t	2026-05-11 04:21:08.59932+00
6a92bbaa-eb8c-43d3-8d66-56881ee0c42e	tata_aig	Tata AIG	🔶	Private	claims@tataaig.com	1800-266-7780	https://www.tataaig.com	\N	t	2026-05-11 04:21:08.59932+00
545b9279-a907-4aeb-877b-7a46e3a4a10f	sbi_general	SBI General	🏛️	PSU	claims@sbigeneral.in	1800-102-1111	https://www.sbigeneral.in	\N	t	2026-05-11 04:21:08.59932+00
e996f634-b831-4236-9423-2ed2ba27486f	oriental_insurance	Oriental Insurance	🌅	PSU	claims@orientalinsurance.co.in	1800-118-485	https://www.orientalinsurance.org.in	\N	t	2026-05-11 04:21:08.59932+00
3e0ff04c-6b09-426c-8f5e-973aa15782ba	max_bupa	Max Bupa	🟣	Private	claims@maxbupa.com	1800-200-5577	https://www.maxbupa.com	\N	t	2026-05-11 04:21:08.59932+00
feff05c6-4936-48bd-9adc-9e2502353b22	manipal_cigna	ManipalCigna	🩺	Private	claims@manipalcigna.com	1800-266-0800	https://www.manipalcigna.com	\N	t	2026-05-11 04:21:08.59932+00
aba63f35-63e3-4a0f-ace5-459adb4437d5	united_india	United India Insurance	🏛️	PSU	claims@uiic.co.in	1800-425-33-33	https://www.uiic.co.in	\N	t	2026-05-11 04:21:08.59932+00
0fdae421-f8f8-4765-b2b0-b4a57021dec7	national_insurance	National Insurance	🏛️	PSU	claims@nic.co.in	1800-345-0330	https://www.nationalinsurance.nic.co.in	\N	t	2026-05-11 04:21:08.59932+00
54f77937-3459-42a2-99ce-8b274d8b242d	iffco_tokio	IFFCO Tokio	🟢	Private	claims@iffcotokio.co.in	1800-103-5499	https://www.iffcotokio.co.in	\N	t	2026-05-11 04:21:08.59932+00
c387b91d-2630-43fa-b143-aea31984991c	reliance_general	Reliance General	🔴	Private	claims@reliancegeneral.co.in	1800-102-1010	https://www.reliancegeneral.co.in	\N	t	2026-05-11 04:21:08.59932+00
dbb33ddb-ae2a-46c6-a685-a0b0979bd365	cholamandalam	Cholamandalam MS	🟡	Private	claims@cholams.murugappa.com	1800-200-5544	https://www.cholainsurance.com	\N	t	2026-05-11 04:21:08.59932+00
24c06fea-956c-47f3-a75c-ae034890d4f3	aditya_birla	Aditya Birla Health	🌐	Private	claims@adityabirlacapital.com	1800-270-7000	https://www.adityabirlahealthinsurance.com	\N	t	2026-05-11 04:21:08.59932+00
33bdc7f8-6fff-4ea7-afe7-875c057ea78f	medi_assist	Medi Assist (TPA)	🏥	TPA	claims@mediassist.in	1800-425-3030	https://www.mediassist.in	\N	t	2026-05-11 04:21:08.59932+00
69570f83-1f37-46de-a0c5-8e27ca93ffbf	paramount_health	Paramount Health (TPA)	🏥	TPA	claims@paramounttpa.com	1800-233-8181	https://www.paramounttpa.com	\N	t	2026-05-11 04:21:08.59932+00
970140aa-d0f5-495d-aac1-917f098cb486	vidal_health	Vidal Health (TPA)	🏥	TPA	claims@vidalhealth.com	1800-425-4033	https://www.vidalhealth.com	\N	t	2026-05-11 04:21:08.59932+00
c0e60806-0146-47b5-bee0-953f7a4dc817	heritage_health	Heritage Health (TPA)	🏥	TPA	claims@heritagehealthtpa.com	1800-102-4488	https://www.heritagehealthtpa.com	\N	t	2026-05-11 04:21:08.59932+00
6b1774c2-e017-43ad-9919-38303ed4e026	md_india	MD India (TPA)	🏥	TPA	claims@maborehealthcaretpa.com	1800-233-3010	https://www.maborehealthcaretpa.com	\N	t	2026-05-11 04:21:08.59932+00
880508e7-cfc1-4709-851b-b6541fea6645	digital_insurance	Go Digit General	💜	Private	claims@godigit.com	1800-258-5956	https://www.godigit.com	\N	t	2026-05-11 04:21:08.59932+00
6af06b0b-7daf-46d6-9cf4-003f4145ae65	kotak_general	Kotak Mahindra General	🔴	Private	claims@kotakgi.com	1800-266-4545	https://www.kotakgeneralinsurance.com	\N	t	2026-05-11 04:21:08.59932+00
\.


--
-- Data for Name: validations; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.validations (id, claim_id, rule_id, rule_name, severity, message, passed, evaluated_at) FROM stdin;
df4c2da7-0d59-4c5a-805b-d218440ddac6	2955fa3a-1aa0-4437-b917-423f90841476	R001	Patient name present	PASS	Patient name found	t	2026-05-11 04:28:31.137013+00
00f2649b-0322-411b-a457-34d0a137a773	2955fa3a-1aa0-4437-b917-423f90841476	R002	Policy number present	ERROR	Policy number is required	f	2026-05-11 04:28:31.137013+00
25b77023-0f46-4baa-b168-4324cf931eb6	2955fa3a-1aa0-4437-b917-423f90841476	R003	Diagnosis present	PASS	Diagnosis found	t	2026-05-11 04:28:31.137013+00
e715ca16-fa86-438e-986b-8ce5b7fecddc	2955fa3a-1aa0-4437-b917-423f90841476	R004	ICD-10 code present	PASS	ICD-10 code found	t	2026-05-11 04:28:31.137013+00
8d922a10-ac98-4b18-965b-a545a429006b	2955fa3a-1aa0-4437-b917-423f90841476	R005	Date of service present	ERROR	Date of service is required	f	2026-05-11 04:28:31.137013+00
74076ae2-4dbd-4c08-960f-e84de9446bb3	2955fa3a-1aa0-4437-b917-423f90841476	R006	Total amount present	PASS	Total amount found	t	2026-05-11 04:28:31.137013+00
da9b3a24-f93b-4fc7-b914-1d0bc5421f5a	2955fa3a-1aa0-4437-b917-423f90841476	R007	Provider name present	PASS	Provider name found	t	2026-05-11 04:28:31.137013+00
1f008b97-31da-43b1-9b34-2b94453db920	2955fa3a-1aa0-4437-b917-423f90841476	R008	Rejection score check	PASS	Rejection risk score acceptable: 0.19	t	2026-05-11 04:28:31.137013+00
93a1cbef-2cf3-464c-b687-4e4b5a2d63b2	2955fa3a-1aa0-4437-b917-423f90841476	R009	CPT code present	PASS	CPT procedure code found	t	2026-05-11 04:28:31.137013+00
4f381b29-d905-49c9-b8d8-1ff2cd30b467	2955fa3a-1aa0-4437-b917-423f90841476	R010	Primary ICD designated	PASS	Primary ICD-10 code designated	t	2026-05-11 04:28:31.137013+00
535ef912-f72a-493c-a673-eb24a22aa6cc	c5568d07-3434-4c94-b892-b963801e95d9	R001	Patient name present	PASS	Patient name found	t	2026-05-11 04:57:25.892428+00
91f8d423-b24c-4055-a5b7-bc23abf8b210	c5568d07-3434-4c94-b892-b963801e95d9	R002	Policy number present	PASS	Policy number found	t	2026-05-11 04:57:25.892428+00
db24f58e-f600-4d31-ab5e-c8dc335cb543	c5568d07-3434-4c94-b892-b963801e95d9	R003	Diagnosis present	PASS	Diagnosis found	t	2026-05-11 04:57:25.892428+00
49669b02-5ae4-4b21-83a9-dd6723e1d7c0	c5568d07-3434-4c94-b892-b963801e95d9	R004	ICD-10 code present	PASS	ICD-10 code found	t	2026-05-11 04:57:25.892428+00
bac9ff5d-5d87-4875-ba2d-8e1c6bf0ca37	c5568d07-3434-4c94-b892-b963801e95d9	R005	Date of service present	PASS	Date of service found	t	2026-05-11 04:57:25.892428+00
491422ff-f4bb-45a2-8fbb-d0a1743fcb83	c5568d07-3434-4c94-b892-b963801e95d9	R006	Total amount present	WARN	Total amount is missing — may delay processing	f	2026-05-11 04:57:25.892428+00
b6c364bc-0c64-4036-9593-534171dc2e48	c5568d07-3434-4c94-b892-b963801e95d9	R007	Provider name present	PASS	Provider name found	t	2026-05-11 04:57:25.892428+00
879c25a9-f3ad-4609-8fd6-5ff17d305d8a	c5568d07-3434-4c94-b892-b963801e95d9	R008	Rejection score check	PASS	Rejection risk score acceptable: 0.18	t	2026-05-11 04:57:25.892428+00
2997ba54-884c-4908-8b4b-1dc4d05d6782	c5568d07-3434-4c94-b892-b963801e95d9	R009	CPT code present	PASS	CPT procedure code found	t	2026-05-11 04:57:25.892428+00
343e8f43-ca20-4a69-8a93-58dd1e4bd114	c5568d07-3434-4c94-b892-b963801e95d9	R010	Primary ICD designated	PASS	Primary ICD-10 code designated	t	2026-05-11 04:57:25.892428+00
054fa571-c9d7-458c-a1e6-94e40330ff7e	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R001	Patient name present	PASS	Patient name found	t	2026-05-11 04:57:53.756436+00
bee62445-5e7d-4a80-94da-6cac667bf253	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R002	Policy number present	ERROR	Policy number is required	f	2026-05-11 04:57:53.756436+00
66acb24a-a714-40c3-b4ee-da6548647b6c	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R003	Diagnosis present	ERROR	At least one diagnosis is required	f	2026-05-11 04:57:53.756436+00
6d7b7a21-33cd-4eb4-a58c-d8cf3f8dd8d8	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R004	ICD-10 code present	ERROR	At least one ICD-10 code is required	f	2026-05-11 04:57:53.756436+00
38f726a2-88af-4412-8129-2b21dec65413	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R005	Date of service present	PASS	Date of service found	t	2026-05-11 04:57:53.756436+00
e6b873c1-629d-4044-8448-f90ab80e0990	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R006	Total amount present	WARN	Total amount is missing — may delay processing	f	2026-05-11 04:57:53.756436+00
e185a2a6-e1b1-4695-8062-95873a13af95	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R007	Provider name present	PASS	Provider name found	t	2026-05-11 04:57:53.756436+00
52891bf8-74ad-4b57-8693-8d3d2dea3e82	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R008	Rejection score check	PASS	Rejection risk score acceptable: 0.43	t	2026-05-11 04:57:53.756436+00
4ca6d69e-6e98-4aa8-8d69-756d7a659954	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R009	CPT code present	WARN	No CPT procedure code found	f	2026-05-11 04:57:53.756436+00
b6d4deb7-a860-454d-9a76-08dc02bceda8	2ba4f78a-c552-47df-8372-3a62cde2e4d1	R010	Primary ICD designated	WARN	No primary ICD-10 code designated	f	2026-05-11 04:57:53.756436+00
0651790b-1802-4916-9fa8-8ce268673603	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R001	Patient name present	PASS	Patient name found	t	2026-05-11 05:01:25.585893+00
a16c990b-6d98-4353-b56e-f5957b766a72	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R002	Policy number present	PASS	Policy number found	t	2026-05-11 05:01:25.585893+00
60f08d1b-40f6-4d2d-9dbf-0772b0fadb1c	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R003	Diagnosis present	PASS	Diagnosis found	t	2026-05-11 05:01:25.585893+00
0ce2bc2f-aa49-4c54-9045-436f6138f377	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R004	ICD-10 code present	PASS	ICD-10 code found	t	2026-05-11 05:01:25.585893+00
97a4fb96-3216-4eb1-ab0b-17941fdcfb4f	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R005	Date of service present	PASS	Date of service found	t	2026-05-11 05:01:25.585893+00
60f5733c-ae93-448b-82d8-4c853e9e5e5b	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R006	Total amount present	WARN	Total amount is missing — may delay processing	f	2026-05-11 05:01:25.585893+00
c0b76b21-1aeb-4451-a255-9511d3bab660	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R007	Provider name present	PASS	Provider name found	t	2026-05-11 05:01:25.585893+00
401d7916-8910-4fd0-803a-dd6dccf6c356	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R008	Rejection score check	PASS	Rejection risk score acceptable: 0.14	t	2026-05-11 05:01:25.585893+00
782ac550-7ac4-46cf-bcfd-d741b2963ca8	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R009	CPT code present	PASS	CPT procedure code found	t	2026-05-11 05:01:25.585893+00
50455656-a760-4e96-a8bc-d3d8fcf40882	647da5fa-9272-4ab8-81f0-b6b57a1886a3	R010	Primary ICD designated	PASS	Primary ICD-10 code designated	t	2026-05-11 05:01:25.585893+00
\.


--
-- Data for Name: workflow_jobs; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.workflow_jobs (id, claim_id, job_type, status, current_step, error_message, retries, started_at, completed_at) FROM stdin;
\.


--
-- Data for Name: workflow_state; Type: TABLE DATA; Schema: public; Owner: claimgpt
--

COPY public.workflow_state (claim_id, current_step, status, updated_at) FROM stdin;
2955fa3a-1aa0-4437-b917-423f90841476	FINISHED	FINISHED	2026-05-11 04:28:31.305302+00
647da5fa-9272-4ab8-81f0-b6b57a1886a3	FINISHED	FINISHED	2026-05-11 05:01:25.758039+00
c5568d07-3434-4c94-b892-b963801e95d9	FINISHED	FINISHED	2026-05-11 04:57:26.071164+00
2ba4f78a-c552-47df-8372-3a62cde2e4d1	FINISHED	FINISHED	2026-05-11 04:57:53.829205+00
\.


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: checkpoint_blobs checkpoint_blobs_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.checkpoint_blobs
    ADD CONSTRAINT checkpoint_blobs_pkey PRIMARY KEY (thread_id, checkpoint_ns, channel, version);


--
-- Name: checkpoint_migrations checkpoint_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.checkpoint_migrations
    ADD CONSTRAINT checkpoint_migrations_pkey PRIMARY KEY (v);


--
-- Name: checkpoint_writes checkpoint_writes_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.checkpoint_writes
    ADD CONSTRAINT checkpoint_writes_pkey PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx);


--
-- Name: checkpoints checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.checkpoints
    ADD CONSTRAINT checkpoints_pkey PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id);


--
-- Name: claims claims_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.claims
    ADD CONSTRAINT claims_pkey PRIMARY KEY (id);


--
-- Name: document_validations document_validations_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.document_validations
    ADD CONSTRAINT document_validations_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: features features_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.features
    ADD CONSTRAINT features_pkey PRIMARY KEY (claim_id);


--
-- Name: medical_codes medical_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.medical_codes
    ADD CONSTRAINT medical_codes_pkey PRIMARY KEY (id);


--
-- Name: medical_entities medical_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.medical_entities
    ADD CONSTRAINT medical_entities_pkey PRIMARY KEY (id);


--
-- Name: ocr_jobs ocr_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.ocr_jobs
    ADD CONSTRAINT ocr_jobs_pkey PRIMARY KEY (id);


--
-- Name: ocr_results ocr_results_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.ocr_results
    ADD CONSTRAINT ocr_results_pkey PRIMARY KEY (id);


--
-- Name: parse_jobs parse_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.parse_jobs
    ADD CONSTRAINT parse_jobs_pkey PRIMARY KEY (id);


--
-- Name: parsed_fields parsed_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.parsed_fields
    ADD CONSTRAINT parsed_fields_pkey PRIMARY KEY (id);


--
-- Name: predictions predictions_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (id);


--
-- Name: scan_analyses scan_analyses_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.scan_analyses
    ADD CONSTRAINT scan_analyses_pkey PRIMARY KEY (id);


--
-- Name: submissions submissions_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.submissions
    ADD CONSTRAINT submissions_pkey PRIMARY KEY (id);


--
-- Name: tpa_providers tpa_providers_code_key; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.tpa_providers
    ADD CONSTRAINT tpa_providers_code_key UNIQUE (code);


--
-- Name: tpa_providers tpa_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.tpa_providers
    ADD CONSTRAINT tpa_providers_pkey PRIMARY KEY (id);


--
-- Name: validations validations_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.validations
    ADD CONSTRAINT validations_pkey PRIMARY KEY (id);


--
-- Name: workflow_jobs workflow_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.workflow_jobs
    ADD CONSTRAINT workflow_jobs_pkey PRIMARY KEY (id);


--
-- Name: workflow_state workflow_state_pkey; Type: CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.workflow_state
    ADD CONSTRAINT workflow_state_pkey PRIMARY KEY (claim_id);


--
-- Name: checkpoint_blobs_thread_id_idx; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX checkpoint_blobs_thread_id_idx ON public.checkpoint_blobs USING btree (thread_id);


--
-- Name: checkpoint_writes_thread_id_idx; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX checkpoint_writes_thread_id_idx ON public.checkpoint_writes USING btree (thread_id);


--
-- Name: checkpoints_thread_id_idx; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX checkpoints_thread_id_idx ON public.checkpoints USING btree (thread_id);


--
-- Name: idx_audit_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_audit_claim_id ON public.audit_logs USING btree (claim_id);


--
-- Name: idx_chat_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_chat_claim_id ON public.chat_messages USING btree (claim_id);


--
-- Name: idx_doc_validations_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_doc_validations_claim_id ON public.document_validations USING btree (claim_id);


--
-- Name: idx_doc_validations_document_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_doc_validations_document_id ON public.document_validations USING btree (document_id);


--
-- Name: idx_doc_validations_status; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_doc_validations_status ON public.document_validations USING btree (status);


--
-- Name: idx_documents_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_documents_claim_id ON public.documents USING btree (claim_id);


--
-- Name: idx_documents_content_hash; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_documents_content_hash ON public.documents USING btree (content_hash);


--
-- Name: idx_medical_codes_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_medical_codes_claim_id ON public.medical_codes USING btree (claim_id);


--
-- Name: idx_medical_entities_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_medical_entities_claim_id ON public.medical_entities USING btree (claim_id);


--
-- Name: idx_ocr_document_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_ocr_document_id ON public.ocr_results USING btree (document_id);


--
-- Name: idx_ocr_jobs_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_ocr_jobs_claim_id ON public.ocr_jobs USING btree (claim_id);


--
-- Name: idx_parse_jobs_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_parse_jobs_claim_id ON public.parse_jobs USING btree (claim_id);


--
-- Name: idx_parse_jobs_set_hash; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_parse_jobs_set_hash ON public.parse_jobs USING btree (set_hash);


--
-- Name: idx_parsed_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_parsed_claim_id ON public.parsed_fields USING btree (claim_id);


--
-- Name: idx_parsed_doc_type; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_parsed_doc_type ON public.parsed_fields USING btree (doc_type);


--
-- Name: idx_parsed_document_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_parsed_document_id ON public.parsed_fields USING btree (document_id);


--
-- Name: idx_predictions_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_predictions_claim_id ON public.predictions USING btree (claim_id);


--
-- Name: idx_scan_analyses_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_scan_analyses_claim_id ON public.scan_analyses USING btree (claim_id);


--
-- Name: idx_scan_analyses_document_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_scan_analyses_document_id ON public.scan_analyses USING btree (document_id);


--
-- Name: idx_submissions_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_submissions_claim_id ON public.submissions USING btree (claim_id);


--
-- Name: idx_tpa_providers_code; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_tpa_providers_code ON public.tpa_providers USING btree (code);


--
-- Name: idx_validations_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_validations_claim_id ON public.validations USING btree (claim_id);


--
-- Name: idx_workflow_claim_id; Type: INDEX; Schema: public; Owner: claimgpt
--

CREATE INDEX idx_workflow_claim_id ON public.workflow_jobs USING btree (claim_id);


--
-- Name: claims trg_claims_updated_at; Type: TRIGGER; Schema: public; Owner: claimgpt
--

CREATE TRIGGER trg_claims_updated_at BEFORE UPDATE ON public.claims FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: chat_messages chat_messages_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: document_validations document_validations_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.document_validations
    ADD CONSTRAINT document_validations_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: document_validations document_validations_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.document_validations
    ADD CONSTRAINT document_validations_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: documents documents_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: features features_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.features
    ADD CONSTRAINT features_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: medical_codes medical_codes_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.medical_codes
    ADD CONSTRAINT medical_codes_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: medical_codes medical_codes_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.medical_codes
    ADD CONSTRAINT medical_codes_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.medical_entities(id);


--
-- Name: medical_entities medical_entities_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.medical_entities
    ADD CONSTRAINT medical_entities_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: ocr_jobs ocr_jobs_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.ocr_jobs
    ADD CONSTRAINT ocr_jobs_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: ocr_results ocr_results_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.ocr_results
    ADD CONSTRAINT ocr_results_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: parse_jobs parse_jobs_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.parse_jobs
    ADD CONSTRAINT parse_jobs_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: parsed_fields parsed_fields_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.parsed_fields
    ADD CONSTRAINT parsed_fields_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: parsed_fields parsed_fields_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.parsed_fields
    ADD CONSTRAINT parsed_fields_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: predictions predictions_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: scan_analyses scan_analyses_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.scan_analyses
    ADD CONSTRAINT scan_analyses_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: scan_analyses scan_analyses_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.scan_analyses
    ADD CONSTRAINT scan_analyses_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: submissions submissions_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.submissions
    ADD CONSTRAINT submissions_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: validations validations_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.validations
    ADD CONSTRAINT validations_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: workflow_jobs workflow_jobs_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.workflow_jobs
    ADD CONSTRAINT workflow_jobs_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- Name: workflow_state workflow_state_claim_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: claimgpt
--

ALTER TABLE ONLY public.workflow_state
    ADD CONSTRAINT workflow_state_claim_id_fkey FOREIGN KEY (claim_id) REFERENCES public.claims(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict QyfQP0cueUoM0OFd4Wb7wnS3IbqVKBxkO3doo1SC57prWF7LACYXzcDazIjG6CY


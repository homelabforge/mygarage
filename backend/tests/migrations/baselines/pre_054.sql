--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: address_book; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.address_book (
    id integer NOT NULL,
    business_name character varying(150) NOT NULL,
    name character varying(100),
    address text,
    city character varying(100),
    state character varying(50),
    zip_code character varying(20),
    phone character varying(20),
    email character varying(100),
    website character varying(200),
    category character varying(50),
    notes text,
    latitude numeric(10,8),
    longitude numeric(11,8),
    source character varying(20) NOT NULL,
    external_id character varying(100),
    rating numeric(3,2),
    user_rating integer,
    usage_count integer NOT NULL,
    last_used timestamp without time zone,
    poi_category character varying(50),
    poi_metadata text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: address_book_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.address_book_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: address_book_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.address_book_id_seq OWNED BY public.address_book.id;


--
-- Name: attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachments (
    id integer NOT NULL,
    record_type character varying(30) NOT NULL,
    record_id integer NOT NULL,
    file_path character varying(255) NOT NULL,
    file_type character varying(10),
    file_size integer,
    uploaded_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_record_type CHECK (((record_type)::text = ANY (ARRAY[('service'::character varying)::text, ('service_visit'::character varying)::text, ('fuel'::character varying)::text, ('upgrade'::character varying)::text, ('collision'::character varying)::text, ('tax'::character varying)::text, ('note'::character varying)::text])))
);


--
-- Name: attachments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.attachments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attachments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.attachments_id_seq OWNED BY public.attachments.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT now() NOT NULL,
    user_id integer,
    username character varying(100),
    action character varying(100) NOT NULL,
    resource_type character varying(50),
    resource_id character varying(255),
    ip_address character varying(45),
    user_agent character varying(500),
    details json,
    success integer NOT NULL,
    error_message text
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: csrf_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.csrf_tokens (
    id integer NOT NULL,
    token character varying(64) NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone NOT NULL
);


--
-- Name: csrf_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.csrf_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: csrf_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.csrf_tokens_id_seq OWNED BY public.csrf_tokens.id;


--
-- Name: def_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.def_records (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    date date NOT NULL,
    odometer_km numeric(10,2),
    liters numeric(9,3),
    cost numeric(8,2),
    price_per_unit numeric(6,3),
    fill_level numeric(3,2),
    source character varying(100),
    brand character varying(100),
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    entry_type character varying(20) DEFAULT 'purchase'::character varying NOT NULL,
    origin_fuel_record_id integer
);


--
-- Name: def_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.def_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: def_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.def_records_id_seq OWNED BY public.def_records.id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    file_path character varying(500) NOT NULL,
    file_name character varying(255) NOT NULL,
    file_size integer NOT NULL,
    mime_type character varying(100) NOT NULL,
    document_type character varying(50),
    title character varying(200) NOT NULL,
    description text,
    uploaded_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;


--
-- Name: drive_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.drive_sessions (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    device_id character varying(20) NOT NULL,
    started_at timestamp without time zone NOT NULL,
    ended_at timestamp without time zone,
    duration_seconds integer,
    start_odometer double precision,
    end_odometer double precision,
    distance_km double precision,
    avg_speed double precision,
    max_speed double precision,
    avg_rpm double precision,
    max_rpm double precision,
    avg_coolant_temp double precision,
    max_coolant_temp double precision,
    avg_throttle double precision,
    max_throttle double precision,
    avg_fuel_level double precision,
    fuel_used_estimate double precision,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: drive_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.drive_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: drive_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.drive_sessions_id_seq OWNED BY public.drive_sessions.id;


--
-- Name: dtc_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dtc_definitions (
    code character varying(10) NOT NULL,
    description text NOT NULL,
    category character varying(20) NOT NULL,
    subcategory character varying(50),
    severity character varying(20) NOT NULL,
    estimated_severity_level integer NOT NULL,
    is_emissions_related boolean NOT NULL,
    common_causes text,
    symptoms text,
    fix_guidance text
);


--
-- Name: fuel_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fuel_records (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    date date NOT NULL,
    odometer_km numeric(10,2),
    liters numeric(9,3),
    propane_liters numeric(9,3),
    tank_size_kg numeric(6,2),
    tank_quantity integer,
    kwh numeric(8,3),
    cost numeric(8,2),
    price_per_unit numeric(6,3),
    price_basis character varying(12),
    fuel_type character varying(50),
    is_full_tank boolean NOT NULL,
    missed_fillup boolean NOT NULL,
    is_hauling boolean NOT NULL,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    propane_gallons numeric(8,3),
    tank_size_lb numeric(6,2)
);


--
-- Name: COLUMN fuel_records.is_hauling; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.fuel_records.is_hauling IS 'Vehicle was towing/hauling during this fuel cycle';


--
-- Name: fuel_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fuel_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fuel_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fuel_records_id_seq OWNED BY public.fuel_records.id;


--
-- Name: insurance_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.insurance_policies (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    provider character varying(100) NOT NULL,
    policy_number character varying(50) NOT NULL,
    policy_type character varying(30) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    premium_amount numeric(10,2),
    premium_frequency character varying(20),
    deductible numeric(10,2),
    coverage_limits text,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    last_notified_at timestamp without time zone,
    CONSTRAINT check_policy_type CHECK (((policy_type)::text = ANY (ARRAY[('Liability'::character varying)::text, ('Comprehensive'::character varying)::text, ('Collision'::character varying)::text, ('Full Coverage'::character varying)::text, ('Minimum'::character varying)::text, ('Other'::character varying)::text]))),
    CONSTRAINT check_premium_frequency CHECK (((premium_frequency)::text = ANY (ARRAY[('Monthly'::character varying)::text, ('Quarterly'::character varying)::text, ('Semi-Annual'::character varying)::text, ('Annual'::character varying)::text])))
);


--
-- Name: insurance_policies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.insurance_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: insurance_policies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.insurance_policies_id_seq OWNED BY public.insurance_policies.id;


--
-- Name: livelink_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.livelink_devices (
    id integer NOT NULL,
    device_id character varying(20) NOT NULL,
    vin character varying(17),
    label character varying(100),
    hw_version character varying(50),
    fw_version character varying(20),
    git_version character varying(20),
    sta_ip character varying(45),
    rssi integer,
    battery_voltage double precision,
    ecu_status character varying(20) NOT NULL,
    device_status character varying(20) NOT NULL,
    device_token_hash character varying(128),
    last_payload_hash character varying(64),
    current_session_id integer,
    pending_offline_at timestamp without time zone,
    enabled boolean NOT NULL,
    last_seen timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: livelink_devices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.livelink_devices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: livelink_devices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.livelink_devices_id_seq OWNED BY public.livelink_devices.id;


--
-- Name: livelink_firmware_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.livelink_firmware_cache (
    id integer NOT NULL,
    latest_version character varying(20),
    latest_tag character varying(20),
    release_url text,
    release_notes text,
    checked_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: livelink_parameters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.livelink_parameters (
    id integer NOT NULL,
    param_key character varying(100) NOT NULL,
    display_name character varying(100),
    unit character varying(20),
    param_class character varying(50),
    category character varying(50),
    icon character varying(50),
    warning_min double precision,
    warning_max double precision,
    display_order integer NOT NULL,
    show_on_dashboard boolean NOT NULL,
    archive_only boolean NOT NULL,
    storage_interval_seconds integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: livelink_parameters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.livelink_parameters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: livelink_parameters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.livelink_parameters_id_seq OWNED BY public.livelink_parameters.id;


--
-- Name: notes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notes (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    date date NOT NULL,
    title character varying(100),
    content text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: notes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.notes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.notes_id_seq OWNED BY public.notes.id;


--
-- Name: odometer_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.odometer_records (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    date date NOT NULL,
    odometer_km numeric(10,2) NOT NULL,
    notes text,
    source character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: odometer_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.odometer_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: odometer_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.odometer_records_id_seq OWNED BY public.odometer_records.id;


--
-- Name: oidc_pending_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oidc_pending_links (
    token character varying(128) NOT NULL,
    username character varying(100) NOT NULL,
    oidc_claims json NOT NULL,
    userinfo_claims json,
    provider_name character varying(100) NOT NULL,
    attempt_count integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone NOT NULL
);


--
-- Name: oidc_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.oidc_states (
    state character varying(128) NOT NULL,
    nonce character varying(128) NOT NULL,
    redirect_uri character varying(512) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    expires_at timestamp without time zone NOT NULL
);


--
-- Name: recalls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recalls (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    nhtsa_campaign_number character varying(20),
    component character varying(100),
    summary text,
    consequence text,
    remedy text,
    date_announced date,
    is_resolved boolean NOT NULL,
    resolved_at timestamp without time zone,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: recalls_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.recalls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recalls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.recalls_id_seq OWNED BY public.recalls.id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    id integer NOT NULL,
    migration_name character varying(255) NOT NULL,
    applied_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: schema_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.schema_migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: schema_migrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.schema_migrations_id_seq OWNED BY public.schema_migrations.id;


--
-- Name: service_line_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.service_line_items (
    id integer NOT NULL,
    visit_id integer NOT NULL,
    description character varying(200) NOT NULL,
    category character varying(30),
    cost numeric(10,2),
    notes text,
    is_inspection boolean NOT NULL,
    inspection_result character varying(20),
    inspection_severity character varying(10),
    triggered_by_inspection_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_inspection_result CHECK (((inspection_result IS NULL) OR ((inspection_result)::text = ANY (ARRAY[('passed'::character varying)::text, ('failed'::character varying)::text, ('needs_attention'::character varying)::text])))),
    CONSTRAINT check_inspection_severity CHECK (((inspection_severity IS NULL) OR ((inspection_severity)::text = ANY (ARRAY[('green'::character varying)::text, ('yellow'::character varying)::text, ('red'::character varying)::text]))))
);


--
-- Name: service_line_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.service_line_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: service_line_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.service_line_items_id_seq OWNED BY public.service_line_items.id;


--
-- Name: service_visits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.service_visits (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    vendor_id integer,
    date date NOT NULL,
    odometer_km numeric(10,2),
    total_cost numeric(10,2),
    tax_amount numeric(10,2),
    shop_supplies numeric(10,2),
    misc_fees numeric(10,2),
    notes text,
    service_category character varying(30),
    insurance_claim_number character varying(50),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone,
    CONSTRAINT check_service_visit_category CHECK (((service_category)::text = ANY (ARRAY[('Maintenance'::character varying)::text, ('Inspection'::character varying)::text, ('Collision'::character varying)::text, ('Upgrades'::character varying)::text, ('Detailing'::character varying)::text])))
);


--
-- Name: service_visits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.service_visits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: service_visits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.service_visits_id_seq OWNED BY public.service_visits.id;


--
-- Name: settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settings (
    key character varying(50) NOT NULL,
    value text,
    category character varying(50) DEFAULT 'general'::character varying NOT NULL,
    description text,
    encrypted boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: spot_rental_billings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spot_rental_billings (
    id integer NOT NULL,
    spot_rental_id integer NOT NULL,
    billing_date date NOT NULL,
    monthly_rate numeric(8,2),
    electric numeric(8,2),
    water numeric(8,2),
    waste numeric(8,2),
    total numeric(10,2),
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: spot_rental_billings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.spot_rental_billings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: spot_rental_billings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.spot_rental_billings_id_seq OWNED BY public.spot_rental_billings.id;


--
-- Name: spot_rentals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.spot_rentals (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    location_name character varying(100),
    location_address text,
    check_in_date date NOT NULL,
    check_out_date date,
    nightly_rate numeric(8,2),
    weekly_rate numeric(8,2),
    monthly_rate numeric(8,2),
    electric numeric(8,2),
    water numeric(8,2),
    waste numeric(8,2),
    total_cost numeric(10,2),
    amenities text,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_spot_rentals_electric_positive CHECK (((electric IS NULL) OR (electric >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_monthly_rate_positive CHECK (((monthly_rate IS NULL) OR (monthly_rate >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_nightly_rate_positive CHECK (((nightly_rate IS NULL) OR (nightly_rate >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_total_cost_positive CHECK (((total_cost IS NULL) OR (total_cost >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_waste_positive CHECK (((waste IS NULL) OR (waste >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_water_positive CHECK (((water IS NULL) OR (water >= (0)::numeric))),
    CONSTRAINT ck_spot_rentals_weekly_rate_positive CHECK (((weekly_rate IS NULL) OR (weekly_rate >= (0)::numeric)))
);


--
-- Name: spot_rentals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.spot_rentals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: spot_rentals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.spot_rentals_id_seq OWNED BY public.spot_rentals.id;


--
-- Name: tax_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tax_records (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    date date NOT NULL,
    tax_type character varying(30),
    amount numeric(10,2) NOT NULL,
    renewal_date date,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT check_tax_type CHECK (((tax_type)::text = ANY (ARRAY[('Registration'::character varying)::text, ('Inspection'::character varying)::text, ('Property Tax'::character varying)::text, ('Tolls'::character varying)::text])))
);


--
-- Name: tax_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tax_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tax_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tax_records_id_seq OWNED BY public.tax_records.id;


--
-- Name: telemetry_daily_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.telemetry_daily_summary (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    param_key character varying(100) NOT NULL,
    date timestamp without time zone NOT NULL,
    min_value double precision,
    max_value double precision,
    avg_value double precision,
    sample_count integer NOT NULL
);


--
-- Name: telemetry_daily_summary_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.telemetry_daily_summary_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: telemetry_daily_summary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.telemetry_daily_summary_id_seq OWNED BY public.telemetry_daily_summary.id;


--
-- Name: toll_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toll_tags (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    toll_system character varying(50) NOT NULL,
    tag_number character varying(50) NOT NULL,
    status character varying(20) NOT NULL,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: toll_tags_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.toll_tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: toll_tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.toll_tags_id_seq OWNED BY public.toll_tags.id;


--
-- Name: toll_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toll_transactions (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    toll_tag_id integer,
    date date NOT NULL,
    amount numeric(8,2) NOT NULL,
    location character varying(200) NOT NULL,
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: toll_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.toll_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: toll_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.toll_transactions_id_seq OWNED BY public.toll_transactions.id;


--
-- Name: trailer_details; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trailer_details (
    vin character varying(17) NOT NULL,
    gvwr_kg numeric(7,2),
    hitch_type character varying(30),
    axle_count integer,
    brake_type character varying(20),
    length_m numeric(5,2),
    width_m numeric(5,2),
    height_m numeric(5,2),
    tow_vehicle_vin character varying(17),
    CONSTRAINT check_brake_type CHECK (((brake_type)::text = ANY (ARRAY[('None'::character varying)::text, ('Electric'::character varying)::text, ('Hydraulic'::character varying)::text]))),
    CONSTRAINT check_hitch_type CHECK (((hitch_type)::text = ANY (ARRAY[('Ball'::character varying)::text, ('Pintle'::character varying)::text, ('Fifth Wheel'::character varying)::text, ('Gooseneck'::character varying)::text])))
);


--
-- Name: tsbs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tsbs (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    tsb_number character varying(50),
    component character varying(200) NOT NULL,
    summary text NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying,
    applied_at timestamp without time zone,
    related_service_id integer,
    source character varying(50) DEFAULT 'manual'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone
);


--
-- Name: tsbs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tsbs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tsbs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tsbs_id_seq OWNED BY public.tsbs.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(100) NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255),
    full_name character varying(255),
    is_active boolean NOT NULL,
    is_admin boolean NOT NULL,
    oidc_subject character varying(255),
    oidc_provider character varying(100),
    auth_method character varying(20) NOT NULL,
    unit_preference character varying(20) NOT NULL,
    show_both_units boolean NOT NULL,
    language character varying(10) NOT NULL,
    currency_code character varying(3) NOT NULL,
    mobile_quick_entry_enabled boolean NOT NULL,
    relationship character varying(50),
    relationship_custom character varying(100),
    show_on_family_dashboard boolean NOT NULL,
    family_dashboard_order integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    last_login timestamp without time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: vehicle_dtcs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_dtcs (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    device_id character varying(20) NOT NULL,
    code character varying(10) NOT NULL,
    description text,
    severity character varying(20) NOT NULL,
    user_notes text,
    first_seen timestamp without time zone DEFAULT now() NOT NULL,
    last_seen timestamp without time zone DEFAULT now() NOT NULL,
    cleared_at timestamp without time zone,
    is_active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_dtcs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_dtcs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_dtcs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_dtcs_id_seq OWNED BY public.vehicle_dtcs.id;


--
-- Name: vehicle_photos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_photos (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    file_path character varying(255) NOT NULL,
    thumbnail_path character varying(255),
    is_main boolean NOT NULL,
    caption character varying(200),
    uploaded_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_photos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_photos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_photos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_photos_id_seq OWNED BY public.vehicle_photos.id;


--
-- Name: vehicle_reminders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_reminders (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    line_item_id integer,
    title character varying(200) NOT NULL,
    reminder_type character varying(10) NOT NULL,
    due_date date,
    due_mileage_km numeric(10,2),
    status character varying(10) NOT NULL,
    notes text,
    last_notified_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_reminders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_reminders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_reminders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_reminders_id_seq OWNED BY public.vehicle_reminders.id;


--
-- Name: vehicle_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_shares (
    id integer NOT NULL,
    vehicle_vin character varying(17) NOT NULL,
    user_id integer NOT NULL,
    permission character varying(10) NOT NULL,
    shared_by integer NOT NULL,
    shared_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_shares_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_shares_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_shares_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_shares_id_seq OWNED BY public.vehicle_shares.id;


--
-- Name: vehicle_telemetry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_telemetry (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    device_id character varying(20) NOT NULL,
    param_key character varying(100) NOT NULL,
    value double precision NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    received_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_telemetry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_telemetry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_telemetry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_telemetry_id_seq OWNED BY public.vehicle_telemetry.id;


--
-- Name: vehicle_telemetry_latest; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_telemetry_latest (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    param_key character varying(100) NOT NULL,
    value double precision NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    received_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vehicle_telemetry_latest_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_telemetry_latest_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_telemetry_latest_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_telemetry_latest_id_seq OWNED BY public.vehicle_telemetry_latest.id;


--
-- Name: vehicle_transfers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicle_transfers (
    id integer NOT NULL,
    vehicle_vin character varying(17) NOT NULL,
    from_user_id integer NOT NULL,
    to_user_id integer NOT NULL,
    transferred_at timestamp without time zone DEFAULT now() NOT NULL,
    transferred_by integer NOT NULL,
    transfer_notes text,
    data_included text
);


--
-- Name: vehicle_transfers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vehicle_transfers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vehicle_transfers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vehicle_transfers_id_seq OWNED BY public.vehicle_transfers.id;


--
-- Name: vehicles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vehicles (
    vin character varying(17) NOT NULL,
    nickname character varying(100) NOT NULL,
    vehicle_type character varying(20) NOT NULL,
    year integer,
    make character varying(50),
    model character varying(50),
    license_plate character varying(20),
    color character varying(30),
    purchase_date date,
    purchase_price numeric(10,2),
    sold_date date,
    sold_price numeric(10,2),
    main_photo character varying(255),
    "trim" character varying(50),
    body_class character varying(100),
    drive_type character varying(30),
    doors integer,
    gvwr_class character varying(50),
    displacement_l character varying(20),
    cylinders integer,
    fuel_type character varying(50),
    transmission_type character varying(50),
    transmission_speeds character varying(20),
    window_sticker_file_path character varying(255),
    window_sticker_uploaded_at timestamp without time zone,
    msrp_base numeric(10,2),
    msrp_options numeric(10,2),
    msrp_total numeric(10,2),
    fuel_economy_city_l_per_100km numeric(5,2),
    fuel_economy_highway_l_per_100km numeric(5,2),
    fuel_economy_combined_l_per_100km numeric(5,2),
    standard_equipment json,
    optional_equipment json,
    assembly_location character varying(100),
    destination_charge numeric(10,2),
    window_sticker_options_detail json,
    window_sticker_packages json,
    exterior_color character varying(100),
    interior_color character varying(100),
    sticker_engine_description character varying(150),
    sticker_transmission_description character varying(150),
    sticker_drivetrain character varying(50),
    wheel_specs character varying(100),
    tire_specs character varying(100),
    warranty_powertrain character varying(100),
    warranty_basic character varying(100),
    environmental_rating_ghg character varying(10),
    environmental_rating_smog character varying(10),
    window_sticker_parser_used character varying(50),
    window_sticker_confidence_score numeric(5,2),
    window_sticker_extracted_vin character varying(17),
    user_id integer,
    archived_at timestamp without time zone,
    archive_reason character varying(50),
    archive_sale_price numeric(10,2),
    archive_sale_date date,
    archive_notes character varying(1000),
    archived_visible boolean DEFAULT true NOT NULL,
    def_tank_capacity_liters numeric(6,2),
    last_milestone_notified_km numeric(10,2),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone,
    fuel_economy_city integer,
    fuel_economy_highway integer,
    fuel_economy_combined integer,
    last_milestone_notified integer,
    CONSTRAINT check_vehicle_type CHECK (((vehicle_type)::text = ANY (ARRAY[('Car'::character varying)::text, ('Truck'::character varying)::text, ('SUV'::character varying)::text, ('Motorcycle'::character varying)::text, ('RV'::character varying)::text, ('Trailer'::character varying)::text, ('FifthWheel'::character varying)::text, ('TravelTrailer'::character varying)::text, ('Electric'::character varying)::text, ('Hybrid'::character varying)::text])))
);


--
-- Name: vendors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vendors (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    address text,
    city character varying(100),
    state character varying(50),
    zip_code character varying(20),
    phone character varying(20),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone
);


--
-- Name: vendors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vendors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vendors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vendors_id_seq OWNED BY public.vendors.id;


--
-- Name: warranty_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.warranty_records (
    id integer NOT NULL,
    vin character varying(17) NOT NULL,
    warranty_type character varying(50) NOT NULL,
    provider character varying(100),
    start_date date NOT NULL,
    end_date date,
    mileage_limit_km numeric(10,2),
    coverage_details text,
    policy_number character varying(50),
    notes text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    last_notified_at timestamp without time zone,
    CONSTRAINT check_warranty_type CHECK (((warranty_type)::text = ANY (ARRAY[('Manufacturer'::character varying)::text, ('Powertrain'::character varying)::text, ('Extended'::character varying)::text, ('Bumper-to-Bumper'::character varying)::text, ('Emissions'::character varying)::text, ('Corrosion'::character varying)::text, ('Other'::character varying)::text])))
);


--
-- Name: warranty_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.warranty_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: warranty_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.warranty_records_id_seq OWNED BY public.warranty_records.id;


--
-- Name: widget_api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.widget_api_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(100) NOT NULL,
    key_hash character varying(64) NOT NULL,
    key_prefix character varying(16) NOT NULL,
    scope character varying(20) NOT NULL,
    allowed_vins json,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    last_used_at timestamp without time zone,
    revoked_at timestamp without time zone
);


--
-- Name: widget_api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.widget_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: widget_api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.widget_api_keys_id_seq OWNED BY public.widget_api_keys.id;


--
-- Name: address_book id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_book ALTER COLUMN id SET DEFAULT nextval('public.address_book_id_seq'::regclass);


--
-- Name: attachments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments ALTER COLUMN id SET DEFAULT nextval('public.attachments_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: csrf_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csrf_tokens ALTER COLUMN id SET DEFAULT nextval('public.csrf_tokens_id_seq'::regclass);


--
-- Name: def_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.def_records ALTER COLUMN id SET DEFAULT nextval('public.def_records_id_seq'::regclass);


--
-- Name: documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);


--
-- Name: drive_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drive_sessions ALTER COLUMN id SET DEFAULT nextval('public.drive_sessions_id_seq'::regclass);


--
-- Name: fuel_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fuel_records ALTER COLUMN id SET DEFAULT nextval('public.fuel_records_id_seq'::regclass);


--
-- Name: insurance_policies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_policies ALTER COLUMN id SET DEFAULT nextval('public.insurance_policies_id_seq'::regclass);


--
-- Name: livelink_devices id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_devices ALTER COLUMN id SET DEFAULT nextval('public.livelink_devices_id_seq'::regclass);


--
-- Name: livelink_parameters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_parameters ALTER COLUMN id SET DEFAULT nextval('public.livelink_parameters_id_seq'::regclass);


--
-- Name: notes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes ALTER COLUMN id SET DEFAULT nextval('public.notes_id_seq'::regclass);


--
-- Name: odometer_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.odometer_records ALTER COLUMN id SET DEFAULT nextval('public.odometer_records_id_seq'::regclass);


--
-- Name: recalls id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recalls ALTER COLUMN id SET DEFAULT nextval('public.recalls_id_seq'::regclass);


--
-- Name: schema_migrations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations ALTER COLUMN id SET DEFAULT nextval('public.schema_migrations_id_seq'::regclass);


--
-- Name: service_line_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_line_items ALTER COLUMN id SET DEFAULT nextval('public.service_line_items_id_seq'::regclass);


--
-- Name: service_visits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_visits ALTER COLUMN id SET DEFAULT nextval('public.service_visits_id_seq'::regclass);


--
-- Name: spot_rental_billings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rental_billings ALTER COLUMN id SET DEFAULT nextval('public.spot_rental_billings_id_seq'::regclass);


--
-- Name: spot_rentals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rentals ALTER COLUMN id SET DEFAULT nextval('public.spot_rentals_id_seq'::regclass);


--
-- Name: tax_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_records ALTER COLUMN id SET DEFAULT nextval('public.tax_records_id_seq'::regclass);


--
-- Name: telemetry_daily_summary id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_daily_summary ALTER COLUMN id SET DEFAULT nextval('public.telemetry_daily_summary_id_seq'::regclass);


--
-- Name: toll_tags id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_tags ALTER COLUMN id SET DEFAULT nextval('public.toll_tags_id_seq'::regclass);


--
-- Name: toll_transactions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_transactions ALTER COLUMN id SET DEFAULT nextval('public.toll_transactions_id_seq'::regclass);


--
-- Name: tsbs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tsbs ALTER COLUMN id SET DEFAULT nextval('public.tsbs_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: vehicle_dtcs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_dtcs ALTER COLUMN id SET DEFAULT nextval('public.vehicle_dtcs_id_seq'::regclass);


--
-- Name: vehicle_photos id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_photos ALTER COLUMN id SET DEFAULT nextval('public.vehicle_photos_id_seq'::regclass);


--
-- Name: vehicle_reminders id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_reminders ALTER COLUMN id SET DEFAULT nextval('public.vehicle_reminders_id_seq'::regclass);


--
-- Name: vehicle_shares id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares ALTER COLUMN id SET DEFAULT nextval('public.vehicle_shares_id_seq'::regclass);


--
-- Name: vehicle_telemetry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry ALTER COLUMN id SET DEFAULT nextval('public.vehicle_telemetry_id_seq'::regclass);


--
-- Name: vehicle_telemetry_latest id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry_latest ALTER COLUMN id SET DEFAULT nextval('public.vehicle_telemetry_latest_id_seq'::regclass);


--
-- Name: vehicle_transfers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers ALTER COLUMN id SET DEFAULT nextval('public.vehicle_transfers_id_seq'::regclass);


--
-- Name: vendors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors ALTER COLUMN id SET DEFAULT nextval('public.vendors_id_seq'::regclass);


--
-- Name: warranty_records id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warranty_records ALTER COLUMN id SET DEFAULT nextval('public.warranty_records_id_seq'::regclass);


--
-- Name: widget_api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.widget_api_keys ALTER COLUMN id SET DEFAULT nextval('public.widget_api_keys_id_seq'::regclass);


--
-- Name: address_book address_book_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_book
    ADD CONSTRAINT address_book_pkey PRIMARY KEY (id);


--
-- Name: attachments attachments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: csrf_tokens csrf_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csrf_tokens
    ADD CONSTRAINT csrf_tokens_pkey PRIMARY KEY (id);


--
-- Name: def_records def_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.def_records
    ADD CONSTRAINT def_records_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: drive_sessions drive_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drive_sessions
    ADD CONSTRAINT drive_sessions_pkey PRIMARY KEY (id);


--
-- Name: dtc_definitions dtc_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dtc_definitions
    ADD CONSTRAINT dtc_definitions_pkey PRIMARY KEY (code);


--
-- Name: fuel_records fuel_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fuel_records
    ADD CONSTRAINT fuel_records_pkey PRIMARY KEY (id);


--
-- Name: insurance_policies insurance_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_policies
    ADD CONSTRAINT insurance_policies_pkey PRIMARY KEY (id);


--
-- Name: livelink_devices livelink_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_devices
    ADD CONSTRAINT livelink_devices_pkey PRIMARY KEY (id);


--
-- Name: livelink_firmware_cache livelink_firmware_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_firmware_cache
    ADD CONSTRAINT livelink_firmware_cache_pkey PRIMARY KEY (id);


--
-- Name: livelink_parameters livelink_parameters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_parameters
    ADD CONSTRAINT livelink_parameters_pkey PRIMARY KEY (id);


--
-- Name: notes notes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_pkey PRIMARY KEY (id);


--
-- Name: odometer_records odometer_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.odometer_records
    ADD CONSTRAINT odometer_records_pkey PRIMARY KEY (id);


--
-- Name: oidc_pending_links oidc_pending_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_pending_links
    ADD CONSTRAINT oidc_pending_links_pkey PRIMARY KEY (token);


--
-- Name: oidc_states oidc_states_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.oidc_states
    ADD CONSTRAINT oidc_states_pkey PRIMARY KEY (state);


--
-- Name: recalls recalls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recalls
    ADD CONSTRAINT recalls_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_migration_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_migration_name_key UNIQUE (migration_name);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (id);


--
-- Name: service_line_items service_line_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_line_items
    ADD CONSTRAINT service_line_items_pkey PRIMARY KEY (id);


--
-- Name: service_visits service_visits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_visits
    ADD CONSTRAINT service_visits_pkey PRIMARY KEY (id);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (key);


--
-- Name: spot_rental_billings spot_rental_billings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rental_billings
    ADD CONSTRAINT spot_rental_billings_pkey PRIMARY KEY (id);


--
-- Name: spot_rentals spot_rentals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rentals
    ADD CONSTRAINT spot_rentals_pkey PRIMARY KEY (id);


--
-- Name: tax_records tax_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_records
    ADD CONSTRAINT tax_records_pkey PRIMARY KEY (id);


--
-- Name: telemetry_daily_summary telemetry_daily_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_daily_summary
    ADD CONSTRAINT telemetry_daily_summary_pkey PRIMARY KEY (id);


--
-- Name: toll_tags toll_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_tags
    ADD CONSTRAINT toll_tags_pkey PRIMARY KEY (id);


--
-- Name: toll_transactions toll_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_transactions
    ADD CONSTRAINT toll_transactions_pkey PRIMARY KEY (id);


--
-- Name: trailer_details trailer_details_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trailer_details
    ADD CONSTRAINT trailer_details_pkey PRIMARY KEY (vin);


--
-- Name: tsbs tsbs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tsbs
    ADD CONSTRAINT tsbs_pkey PRIMARY KEY (id);


--
-- Name: telemetry_daily_summary uq_daily_summary_vin_param_date; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_daily_summary
    ADD CONSTRAINT uq_daily_summary_vin_param_date UNIQUE (vin, param_key, date);


--
-- Name: vehicle_telemetry uq_telemetry_dedup; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry
    ADD CONSTRAINT uq_telemetry_dedup UNIQUE (device_id, param_key, "timestamp");


--
-- Name: vehicle_telemetry_latest uq_telemetry_latest_vin_param; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry_latest
    ADD CONSTRAINT uq_telemetry_latest_vin_param UNIQUE (vin, param_key);


--
-- Name: vehicle_shares uq_vehicle_shares_vin_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares
    ADD CONSTRAINT uq_vehicle_shares_vin_user UNIQUE (vehicle_vin, user_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: vehicle_dtcs vehicle_dtcs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_dtcs
    ADD CONSTRAINT vehicle_dtcs_pkey PRIMARY KEY (id);


--
-- Name: vehicle_photos vehicle_photos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_photos
    ADD CONSTRAINT vehicle_photos_pkey PRIMARY KEY (id);


--
-- Name: vehicle_reminders vehicle_reminders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_reminders
    ADD CONSTRAINT vehicle_reminders_pkey PRIMARY KEY (id);


--
-- Name: vehicle_shares vehicle_shares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares
    ADD CONSTRAINT vehicle_shares_pkey PRIMARY KEY (id);


--
-- Name: vehicle_telemetry_latest vehicle_telemetry_latest_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry_latest
    ADD CONSTRAINT vehicle_telemetry_latest_pkey PRIMARY KEY (id);


--
-- Name: vehicle_telemetry vehicle_telemetry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry
    ADD CONSTRAINT vehicle_telemetry_pkey PRIMARY KEY (id);


--
-- Name: vehicle_transfers vehicle_transfers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers
    ADD CONSTRAINT vehicle_transfers_pkey PRIMARY KEY (id);


--
-- Name: vehicles vehicles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_pkey PRIMARY KEY (vin);


--
-- Name: vendors vendors_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors
    ADD CONSTRAINT vendors_name_key UNIQUE (name);


--
-- Name: vendors vendors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vendors
    ADD CONSTRAINT vendors_pkey PRIMARY KEY (id);


--
-- Name: warranty_records warranty_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warranty_records
    ADD CONSTRAINT warranty_records_pkey PRIMARY KEY (id);


--
-- Name: widget_api_keys widget_api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.widget_api_keys
    ADD CONSTRAINT widget_api_keys_pkey PRIMARY KEY (id);


--
-- Name: idx_address_book_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_address_book_category ON public.address_book USING btree (category);


--
-- Name: idx_address_book_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_address_book_name ON public.address_book USING btree (name);


--
-- Name: idx_address_book_poi_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_address_book_poi_category ON public.address_book USING btree (poi_category);


--
-- Name: idx_attachments_record; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attachments_record ON public.attachments USING btree (record_type, record_id);


--
-- Name: idx_csrf_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_csrf_token ON public.csrf_tokens USING btree (token);


--
-- Name: idx_csrf_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_csrf_user_id ON public.csrf_tokens USING btree (user_id);


--
-- Name: idx_daily_summary_param; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_summary_param ON public.telemetry_daily_summary USING btree (vin, param_key, date);


--
-- Name: idx_daily_summary_vehicle_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_daily_summary_vehicle_date ON public.telemetry_daily_summary USING btree (vin, date);


--
-- Name: idx_def_entry_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_entry_type ON public.def_records USING btree (entry_type);


--
-- Name: idx_def_origin_fuel_record_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_origin_fuel_record_id ON public.def_records USING btree (origin_fuel_record_id);


--
-- Name: idx_def_records_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_records_date ON public.def_records USING btree (date);


--
-- Name: idx_def_records_odometer_km; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_records_odometer_km ON public.def_records USING btree (odometer_km);


--
-- Name: idx_def_records_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_records_vin ON public.def_records USING btree (vin);


--
-- Name: idx_def_records_vin_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_def_records_vin_date ON public.def_records USING btree (vin, date);


--
-- Name: idx_documents_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_type ON public.documents USING btree (document_type);


--
-- Name: idx_documents_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_vin ON public.documents USING btree (vin);


--
-- Name: idx_dtc_defs_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtc_defs_category ON public.dtc_definitions USING btree (category);


--
-- Name: idx_dtc_defs_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtc_defs_severity ON public.dtc_definitions USING btree (severity);


--
-- Name: idx_dtcs_device; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtcs_device ON public.vehicle_dtcs USING btree (device_id);


--
-- Name: idx_dtcs_first_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtcs_first_seen ON public.vehicle_dtcs USING btree (first_seen);


--
-- Name: idx_dtcs_vehicle_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtcs_vehicle_active ON public.vehicle_dtcs USING btree (vin, is_active);


--
-- Name: idx_dtcs_vehicle_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dtcs_vehicle_code ON public.vehicle_dtcs USING btree (vin, code);


--
-- Name: idx_fuel_full_tank_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_full_tank_vin ON public.fuel_records USING btree (vin, is_full_tank);


--
-- Name: idx_fuel_hauling; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_hauling ON public.fuel_records USING btree (is_hauling);


--
-- Name: idx_fuel_is_full_tank; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_is_full_tank ON public.fuel_records USING btree (is_full_tank);


--
-- Name: idx_fuel_normal_mpg; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_normal_mpg ON public.fuel_records USING btree (vin, is_full_tank, is_hauling);


--
-- Name: idx_fuel_records_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_records_date ON public.fuel_records USING btree (date);


--
-- Name: idx_fuel_records_odometer_km; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_records_odometer_km ON public.fuel_records USING btree (odometer_km);


--
-- Name: idx_fuel_records_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_records_vin ON public.fuel_records USING btree (vin);


--
-- Name: idx_fuel_vin_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fuel_vin_date ON public.fuel_records USING btree (vin, date);


--
-- Name: idx_insurance_policies_end_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insurance_policies_end_date ON public.insurance_policies USING btree (end_date);


--
-- Name: idx_insurance_policies_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_insurance_policies_vin ON public.insurance_policies USING btree (vin);


--
-- Name: idx_livelink_devices_last_seen; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_devices_last_seen ON public.livelink_devices USING btree (last_seen);


--
-- Name: idx_livelink_devices_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_devices_status ON public.livelink_devices USING btree (device_status);


--
-- Name: idx_livelink_devices_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_devices_vin ON public.livelink_devices USING btree (vin);


--
-- Name: idx_livelink_params_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_params_category ON public.livelink_parameters USING btree (category);


--
-- Name: idx_livelink_params_class; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_params_class ON public.livelink_parameters USING btree (param_class);


--
-- Name: idx_livelink_params_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_livelink_params_order ON public.livelink_parameters USING btree (display_order);


--
-- Name: idx_notes_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notes_date ON public.notes USING btree (date);


--
-- Name: idx_notes_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_notes_vin ON public.notes USING btree (vin);


--
-- Name: idx_odometer_records_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_records_date ON public.odometer_records USING btree (date);


--
-- Name: idx_odometer_records_odometer_km; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_records_odometer_km ON public.odometer_records USING btree (odometer_km);


--
-- Name: idx_odometer_records_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_records_vin ON public.odometer_records USING btree (vin);


--
-- Name: idx_odometer_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_source ON public.odometer_records USING btree (source);


--
-- Name: idx_odometer_vin_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_vin_date ON public.odometer_records USING btree (vin, date);


--
-- Name: idx_odometer_vin_odometer_km; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_odometer_vin_odometer_km ON public.odometer_records USING btree (vin, odometer_km);


--
-- Name: idx_recalls_resolved; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recalls_resolved ON public.recalls USING btree (is_resolved);


--
-- Name: idx_recalls_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_recalls_vin ON public.recalls USING btree (vin);


--
-- Name: idx_service_line_items_visit; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_service_line_items_visit ON public.service_line_items USING btree (visit_id);


--
-- Name: idx_service_visits_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_service_visits_date ON public.service_visits USING btree (date);


--
-- Name: idx_service_visits_vendor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_service_visits_vendor ON public.service_visits USING btree (vendor_id);


--
-- Name: idx_service_visits_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_service_visits_vin ON public.service_visits USING btree (vin);


--
-- Name: idx_service_visits_vin_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_service_visits_vin_date ON public.service_visits USING btree (vin, date);


--
-- Name: idx_sessions_device; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_device ON public.drive_sessions USING btree (device_id, started_at);


--
-- Name: idx_sessions_ended; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_ended ON public.drive_sessions USING btree (ended_at);


--
-- Name: idx_sessions_vehicle_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sessions_vehicle_time ON public.drive_sessions USING btree (vin, started_at);


--
-- Name: idx_spot_rental_billings_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spot_rental_billings_date ON public.spot_rental_billings USING btree (billing_date);


--
-- Name: idx_spot_rental_billings_rental_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spot_rental_billings_rental_id ON public.spot_rental_billings USING btree (spot_rental_id);


--
-- Name: idx_spot_rentals_dates; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spot_rentals_dates ON public.spot_rentals USING btree (check_in_date, check_out_date);


--
-- Name: idx_spot_rentals_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_spot_rentals_vin ON public.spot_rentals USING btree (vin);


--
-- Name: idx_tax_records_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tax_records_date ON public.tax_records USING btree (date);


--
-- Name: idx_tax_records_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tax_records_vin ON public.tax_records USING btree (vin);


--
-- Name: idx_telemetry_device; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telemetry_device ON public.vehicle_telemetry USING btree (device_id, "timestamp");


--
-- Name: idx_telemetry_latest_vehicle; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telemetry_latest_vehicle ON public.vehicle_telemetry_latest USING btree (vin);


--
-- Name: idx_telemetry_param_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telemetry_param_time ON public.vehicle_telemetry USING btree (vin, param_key, "timestamp");


--
-- Name: idx_telemetry_vehicle_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telemetry_vehicle_time ON public.vehicle_telemetry USING btree (vin, "timestamp");


--
-- Name: idx_toll_tags_tag_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_toll_tags_tag_number ON public.toll_tags USING btree (tag_number);


--
-- Name: idx_toll_tags_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_toll_tags_vin ON public.toll_tags USING btree (vin);


--
-- Name: idx_toll_transactions_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_toll_transactions_date ON public.toll_transactions USING btree (date);


--
-- Name: idx_toll_transactions_toll_tag_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_toll_transactions_toll_tag_id ON public.toll_transactions USING btree (toll_tag_id);


--
-- Name: idx_toll_transactions_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_toll_transactions_vin ON public.toll_transactions USING btree (vin);


--
-- Name: idx_tsbs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tsbs_status ON public.tsbs USING btree (status);


--
-- Name: idx_tsbs_tsb_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tsbs_tsb_number ON public.tsbs USING btree (tsb_number);


--
-- Name: idx_tsbs_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tsbs_vin ON public.tsbs USING btree (vin);


--
-- Name: idx_users_auth_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_auth_method ON public.users USING btree (auth_method);


--
-- Name: idx_users_oidc_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_oidc_provider ON public.users USING btree (oidc_provider) WHERE (oidc_provider IS NOT NULL);


--
-- Name: idx_users_oidc_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_users_oidc_subject ON public.users USING btree (oidc_subject) WHERE (oidc_subject IS NOT NULL);


--
-- Name: idx_vehicle_photos_main; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vehicle_photos_main ON public.vehicle_photos USING btree (is_main);


--
-- Name: idx_vehicle_photos_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vehicle_photos_vin ON public.vehicle_photos USING btree (vin);


--
-- Name: idx_vehicles_nickname; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vehicles_nickname ON public.vehicles USING btree (nickname);


--
-- Name: idx_vehicles_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vehicles_type ON public.vehicles USING btree (vehicle_type);


--
-- Name: idx_vendors_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vendors_name ON public.vendors USING btree (name);


--
-- Name: idx_warranty_records_end_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_warranty_records_end_date ON public.warranty_records USING btree (end_date);


--
-- Name: idx_warranty_records_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_warranty_records_vin ON public.warranty_records USING btree (vin);


--
-- Name: ix_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);


--
-- Name: ix_audit_logs_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_id ON public.audit_logs USING btree (id);


--
-- Name: ix_audit_logs_resource_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_resource_type ON public.audit_logs USING btree (resource_type);


--
-- Name: ix_audit_logs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_timestamp ON public.audit_logs USING btree ("timestamp");


--
-- Name: ix_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: ix_csrf_tokens_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_csrf_tokens_id ON public.csrf_tokens USING btree (id);


--
-- Name: ix_csrf_tokens_token; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_csrf_tokens_token ON public.csrf_tokens USING btree (token);


--
-- Name: ix_csrf_user_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_csrf_user_token ON public.csrf_tokens USING btree (user_id, token);


--
-- Name: ix_livelink_devices_device_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_livelink_devices_device_id ON public.livelink_devices USING btree (device_id);


--
-- Name: ix_livelink_parameters_param_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_livelink_parameters_param_key ON public.livelink_parameters USING btree (param_key);


--
-- Name: ix_oidc_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_expires_at ON public.oidc_states USING btree (expires_at);


--
-- Name: ix_oidc_pending_link_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_pending_link_expires_at ON public.oidc_pending_links USING btree (expires_at);


--
-- Name: ix_oidc_pending_link_username; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_pending_link_username ON public.oidc_pending_links USING btree (username);


--
-- Name: ix_oidc_pending_links_token; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_pending_links_token ON public.oidc_pending_links USING btree (token);


--
-- Name: ix_oidc_pending_links_username; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_pending_links_username ON public.oidc_pending_links USING btree (username);


--
-- Name: ix_oidc_states_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_oidc_states_state ON public.oidc_states USING btree (state);


--
-- Name: ix_reminders_due_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reminders_due_date ON public.vehicle_reminders USING btree (due_date);


--
-- Name: ix_reminders_due_mileage_km; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reminders_due_mileage_km ON public.vehicle_reminders USING btree (due_mileage_km);


--
-- Name: ix_reminders_vin_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_reminders_vin_status ON public.vehicle_reminders USING btree (vin, status);


--
-- Name: ix_users_auth_method; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_auth_method ON public.users USING btree (auth_method);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: ix_users_oidc_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_oidc_provider ON public.users USING btree (oidc_provider);


--
-- Name: ix_users_oidc_subject; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_oidc_subject ON public.users USING btree (oidc_subject);


--
-- Name: ix_users_username; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);


--
-- Name: ix_vehicle_shares_shared_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_shares_shared_by ON public.vehicle_shares USING btree (shared_by);


--
-- Name: ix_vehicle_shares_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_shares_user_id ON public.vehicle_shares USING btree (user_id);


--
-- Name: ix_vehicle_shares_vehicle_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_shares_vehicle_vin ON public.vehicle_shares USING btree (vehicle_vin);


--
-- Name: ix_vehicle_transfers_from_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_transfers_from_user_id ON public.vehicle_transfers USING btree (from_user_id);


--
-- Name: ix_vehicle_transfers_to_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_transfers_to_user_id ON public.vehicle_transfers USING btree (to_user_id);


--
-- Name: ix_vehicle_transfers_transferred_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_transfers_transferred_at ON public.vehicle_transfers USING btree (transferred_at);


--
-- Name: ix_vehicle_transfers_vehicle_vin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicle_transfers_vehicle_vin ON public.vehicle_transfers USING btree (vehicle_vin);


--
-- Name: ix_vehicles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vehicles_user_id ON public.vehicles USING btree (user_id);


--
-- Name: ix_widget_api_keys_key_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_widget_api_keys_key_hash ON public.widget_api_keys USING btree (key_hash);


--
-- Name: ix_widget_api_keys_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_widget_api_keys_user_id ON public.widget_api_keys USING btree (user_id);


--
-- Name: csrf_tokens csrf_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csrf_tokens
    ADD CONSTRAINT csrf_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: def_records def_records_origin_fuel_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.def_records
    ADD CONSTRAINT def_records_origin_fuel_record_id_fkey FOREIGN KEY (origin_fuel_record_id) REFERENCES public.fuel_records(id) ON DELETE SET NULL;


--
-- Name: def_records def_records_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.def_records
    ADD CONSTRAINT def_records_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: documents documents_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: drive_sessions drive_sessions_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.drive_sessions
    ADD CONSTRAINT drive_sessions_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: fuel_records fuel_records_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fuel_records
    ADD CONSTRAINT fuel_records_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: insurance_policies insurance_policies_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.insurance_policies
    ADD CONSTRAINT insurance_policies_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: livelink_devices livelink_devices_current_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_devices
    ADD CONSTRAINT livelink_devices_current_session_id_fkey FOREIGN KEY (current_session_id) REFERENCES public.drive_sessions(id) ON DELETE SET NULL;


--
-- Name: livelink_devices livelink_devices_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.livelink_devices
    ADD CONSTRAINT livelink_devices_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE SET NULL;


--
-- Name: notes notes_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notes
    ADD CONSTRAINT notes_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: odometer_records odometer_records_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.odometer_records
    ADD CONSTRAINT odometer_records_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: recalls recalls_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recalls
    ADD CONSTRAINT recalls_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: service_line_items service_line_items_triggered_by_inspection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_line_items
    ADD CONSTRAINT service_line_items_triggered_by_inspection_id_fkey FOREIGN KEY (triggered_by_inspection_id) REFERENCES public.service_line_items(id);


--
-- Name: service_line_items service_line_items_visit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_line_items
    ADD CONSTRAINT service_line_items_visit_id_fkey FOREIGN KEY (visit_id) REFERENCES public.service_visits(id) ON DELETE CASCADE;


--
-- Name: service_visits service_visits_vendor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_visits
    ADD CONSTRAINT service_visits_vendor_id_fkey FOREIGN KEY (vendor_id) REFERENCES public.vendors(id);


--
-- Name: service_visits service_visits_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.service_visits
    ADD CONSTRAINT service_visits_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: spot_rental_billings spot_rental_billings_spot_rental_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rental_billings
    ADD CONSTRAINT spot_rental_billings_spot_rental_id_fkey FOREIGN KEY (spot_rental_id) REFERENCES public.spot_rentals(id) ON DELETE CASCADE;


--
-- Name: spot_rentals spot_rentals_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.spot_rentals
    ADD CONSTRAINT spot_rentals_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: tax_records tax_records_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tax_records
    ADD CONSTRAINT tax_records_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: telemetry_daily_summary telemetry_daily_summary_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telemetry_daily_summary
    ADD CONSTRAINT telemetry_daily_summary_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: toll_tags toll_tags_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_tags
    ADD CONSTRAINT toll_tags_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: toll_transactions toll_transactions_toll_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_transactions
    ADD CONSTRAINT toll_transactions_toll_tag_id_fkey FOREIGN KEY (toll_tag_id) REFERENCES public.toll_tags(id) ON DELETE SET NULL;


--
-- Name: toll_transactions toll_transactions_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_transactions
    ADD CONSTRAINT toll_transactions_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: trailer_details trailer_details_tow_vehicle_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trailer_details
    ADD CONSTRAINT trailer_details_tow_vehicle_vin_fkey FOREIGN KEY (tow_vehicle_vin) REFERENCES public.vehicles(vin) ON DELETE SET NULL;


--
-- Name: trailer_details trailer_details_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trailer_details
    ADD CONSTRAINT trailer_details_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: tsbs tsbs_related_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tsbs
    ADD CONSTRAINT tsbs_related_service_id_fkey FOREIGN KEY (related_service_id) REFERENCES public.service_visits(id) ON DELETE SET NULL;


--
-- Name: tsbs tsbs_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tsbs
    ADD CONSTRAINT tsbs_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_dtcs vehicle_dtcs_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_dtcs
    ADD CONSTRAINT vehicle_dtcs_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_photos vehicle_photos_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_photos
    ADD CONSTRAINT vehicle_photos_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_reminders vehicle_reminders_line_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_reminders
    ADD CONSTRAINT vehicle_reminders_line_item_id_fkey FOREIGN KEY (line_item_id) REFERENCES public.service_line_items(id) ON DELETE SET NULL;


--
-- Name: vehicle_reminders vehicle_reminders_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_reminders
    ADD CONSTRAINT vehicle_reminders_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_shares vehicle_shares_shared_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares
    ADD CONSTRAINT vehicle_shares_shared_by_fkey FOREIGN KEY (shared_by) REFERENCES public.users(id);


--
-- Name: vehicle_shares vehicle_shares_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares
    ADD CONSTRAINT vehicle_shares_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: vehicle_shares vehicle_shares_vehicle_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_shares
    ADD CONSTRAINT vehicle_shares_vehicle_vin_fkey FOREIGN KEY (vehicle_vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_telemetry_latest vehicle_telemetry_latest_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry_latest
    ADD CONSTRAINT vehicle_telemetry_latest_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_telemetry vehicle_telemetry_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_telemetry
    ADD CONSTRAINT vehicle_telemetry_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicle_transfers vehicle_transfers_from_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers
    ADD CONSTRAINT vehicle_transfers_from_user_id_fkey FOREIGN KEY (from_user_id) REFERENCES public.users(id);


--
-- Name: vehicle_transfers vehicle_transfers_to_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers
    ADD CONSTRAINT vehicle_transfers_to_user_id_fkey FOREIGN KEY (to_user_id) REFERENCES public.users(id);


--
-- Name: vehicle_transfers vehicle_transfers_transferred_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers
    ADD CONSTRAINT vehicle_transfers_transferred_by_fkey FOREIGN KEY (transferred_by) REFERENCES public.users(id);


--
-- Name: vehicle_transfers vehicle_transfers_vehicle_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicle_transfers
    ADD CONSTRAINT vehicle_transfers_vehicle_vin_fkey FOREIGN KEY (vehicle_vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: vehicles vehicles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vehicles
    ADD CONSTRAINT vehicles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: warranty_records warranty_records_vin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.warranty_records
    ADD CONSTRAINT warranty_records_vin_fkey FOREIGN KEY (vin) REFERENCES public.vehicles(vin) ON DELETE CASCADE;


--
-- Name: widget_api_keys widget_api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.widget_api_keys
    ADD CONSTRAINT widget_api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: schema_migrations; Type: TABLE DATA; Schema: public; Owner: mygarage
--

INSERT INTO public.schema_migrations VALUES (1, '001_add_vin_fields', '2026-05-05 12:42:31.533868');
INSERT INTO public.schema_migrations VALUES (2, '002_update_address_book_schema', '2026-05-05 12:42:31.536955');
INSERT INTO public.schema_migrations VALUES (3, '003_add_window_sticker_fields', '2026-05-05 12:42:31.543143');
INSERT INTO public.schema_migrations VALUES (4, '004_add_window_sticker_enhanced_fields', '2026-05-05 12:42:31.547218');
INSERT INTO public.schema_migrations VALUES (5, '005_add_vehicle_photo_thumbnails', '2026-05-05 12:42:31.550568');
INSERT INTO public.schema_migrations VALUES (6, '006_update_service_type_constraint', '2026-05-05 12:42:31.551686');
INSERT INTO public.schema_migrations VALUES (7, '007_add_fuel_hauling_column', '2026-05-05 12:42:31.554722');
INSERT INTO public.schema_migrations VALUES (8, '008_add_spot_rental_utilities', '2026-05-05 12:42:31.557573');
INSERT INTO public.schema_migrations VALUES (9, '009_add_fuel_propane_column', '2026-05-05 12:42:31.560292');
INSERT INTO public.schema_migrations VALUES (10, '010_migrate_to_argon2', '2026-05-05 12:42:31.565886');
INSERT INTO public.schema_migrations VALUES (11, '011_add_oidc_fields', '2026-05-05 12:42:31.574927');
INSERT INTO public.schema_migrations VALUES (12, '012_security_hardening', '2026-05-05 12:42:31.577297');
INSERT INTO public.schema_migrations VALUES (13, '013_add_user_id_to_vehicles', '2026-05-05 12:42:31.579793');
INSERT INTO public.schema_migrations VALUES (14, '014_hydrate_legacy_photos', '2026-05-05 12:42:31.609526');
INSERT INTO public.schema_migrations VALUES (15, '015_add_oidc_pending_links', '2026-05-05 12:42:31.611234');
INSERT INTO public.schema_migrations VALUES (16, '016_add_unit_preference', '2026-05-05 12:42:31.61378');
INSERT INTO public.schema_migrations VALUES (17, '017_add_vehicle_archive', '2026-05-05 12:42:31.616234');
INSERT INTO public.schema_migrations VALUES (18, '018_add_spot_rental_billings', '2026-05-05 12:42:31.61699');
INSERT INTO public.schema_migrations VALUES (19, '019_add_ev_support', '2026-05-05 12:42:31.619037');
INSERT INTO public.schema_migrations VALUES (20, '020_add_travel_trailer_type', '2026-05-05 12:42:31.619402');
INSERT INTO public.schema_migrations VALUES (21, '021_add_propane_tank_columns', '2026-05-05 12:42:31.621647');
INSERT INTO public.schema_migrations VALUES (22, '022_redesign_service_type_schema', '2026-05-05 12:42:31.622648');
INSERT INTO public.schema_migrations VALUES (23, '023_add_maintenance_templates', '2026-05-05 12:42:31.6233');
INSERT INTO public.schema_migrations VALUES (24, '024_add_tsbs_table', '2026-05-05 12:42:31.626537');
INSERT INTO public.schema_migrations VALUES (25, '025_add_shop_finder_fields', '2026-05-05 12:42:31.629048');
INSERT INTO public.schema_migrations VALUES (26, '026_add_detailing_category', '2026-05-05 12:42:31.630026');
INSERT INTO public.schema_migrations VALUES (27, '027_add_poi_support', '2026-05-05 12:42:31.633629');
INSERT INTO public.schema_migrations VALUES (28, '028_maintenance_overhaul', '2026-05-05 12:42:31.640593');
INSERT INTO public.schema_migrations VALUES (29, '029_cleanup_migrated_reminders', '2026-05-05 12:42:31.641301');
INSERT INTO public.schema_migrations VALUES (30, '030_migrate_service_attachments', '2026-05-05 12:42:31.643313');
INSERT INTO public.schema_migrations VALUES (31, '031_add_service_cost_breakdown', '2026-05-05 12:42:31.645682');
INSERT INTO public.schema_migrations VALUES (32, '032_add_livelink_tables', '2026-05-05 12:42:31.648076');
INSERT INTO public.schema_migrations VALUES (33, '033_seed_dtc_definitions', '2026-05-05 12:42:31.648682');
INSERT INTO public.schema_migrations VALUES (34, '034_add_livelink_settings', '2026-05-05 12:42:31.650452');
INSERT INTO public.schema_migrations VALUES (35, '035_add_odometer_source', '2026-05-05 12:42:31.654144');
INSERT INTO public.schema_migrations VALUES (36, '036_add_mqtt_settings', '2026-05-05 12:42:31.655765');
INSERT INTO public.schema_migrations VALUES (37, '037_add_family_multiuser_system', '2026-05-05 12:42:31.658656');
INSERT INTO public.schema_migrations VALUES (38, '038_add_def_tracking', '2026-05-05 12:42:31.662442');
INSERT INTO public.schema_migrations VALUES (39, '039_backfill_service_visit_totals', '2026-05-05 12:42:31.663365');
INSERT INTO public.schema_migrations VALUES (40, '040_drop_service_records_table', '2026-05-05 12:42:31.664001');
INSERT INTO public.schema_migrations VALUES (41, '041_add_def_entry_type_and_fuel_link', '2026-05-05 12:42:31.667185');
INSERT INTO public.schema_migrations VALUES (42, '042_add_session_grace_period', '2026-05-05 12:42:31.669612');
INSERT INTO public.schema_migrations VALUES (43, '043_add_mobile_quick_entry_preference', '2026-05-05 12:42:31.671781');
INSERT INTO public.schema_migrations VALUES (44, '044_sync_address_book_to_vendors', '2026-05-05 12:42:31.673289');
INSERT INTO public.schema_migrations VALUES (45, '045_drop_reminders_table', '2026-05-05 12:42:31.674469');
INSERT INTO public.schema_migrations VALUES (46, '046_add_notification_tracking', '2026-05-05 12:42:31.679656');
INSERT INTO public.schema_migrations VALUES (47, '047_add_vehicle_milestone_tracking', '2026-05-05 12:42:31.682529');
INSERT INTO public.schema_migrations VALUES (48, '048_service_visit_overhaul', '2026-05-05 12:42:31.687148');
INSERT INTO public.schema_migrations VALUES (49, '049_remove_maintenance_schedule', '2026-05-05 12:42:31.695254');
INSERT INTO public.schema_migrations VALUES (50, '050_fix_service_line_items_schema', '2026-05-05 12:42:31.695804');
INSERT INTO public.schema_migrations VALUES (51, '051_add_i18n_user_preferences', '2026-05-05 12:42:31.69801');
INSERT INTO public.schema_migrations VALUES (52, '052_add_widget_api_keys', '2026-05-05 12:42:31.698751');
INSERT INTO public.schema_migrations VALUES (53, '053_metric_canonical_units', '2026-05-05 12:42:31.702401');


--
-- Name: schema_migrations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: mygarage
--

SELECT pg_catalog.setval('public.schema_migrations_id_seq', 53, true);


--
-- PostgreSQL database dump complete
--



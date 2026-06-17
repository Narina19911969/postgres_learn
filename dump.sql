--
-- PostgreSQL database dump
--

\restrict nNwjQFu6E5IxnU3lae6yfPhjZDTYRb4MYADBNiBdhY3Qzf4dmD8EAJ73ApRFEKO

-- Dumped from database version 18.3 (Debian 18.3-1.pgdg12+1)
-- Dumped by pg_dump version 18.4 (Ubuntu 18.4-1.pgdg22.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: product_categories; Type: TABLE; Schema: catalog; Owner: app_user
--

CREATE TABLE catalog.product_categories (
    id integer NOT NULL,
    name character varying(255) NOT NULL
);


ALTER TABLE catalog.product_categories OWNER TO app_user;

--
-- Name: product_categories_id_seq; Type: SEQUENCE; Schema: catalog; Owner: app_user
--

CREATE SEQUENCE catalog.product_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE catalog.product_categories_id_seq OWNER TO app_user;

--
-- Name: product_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: app_user
--

ALTER SEQUENCE catalog.product_categories_id_seq OWNED BY catalog.product_categories.id;


--
-- Name: products; Type: TABLE; Schema: catalog; Owner: app_user
--

CREATE TABLE catalog.products (
    id integer NOT NULL,
    sku character varying(30) NOT NULL,
    name character varying(255) NOT NULL,
    price numeric NOT NULL,
    category_id integer NOT NULL
);


ALTER TABLE catalog.products OWNER TO app_user;

--
-- Name: products_id_seq; Type: SEQUENCE; Schema: catalog; Owner: app_user
--

CREATE SEQUENCE catalog.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE catalog.products_id_seq OWNER TO app_user;

--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: app_user
--

ALTER SEQUENCE catalog.products_id_seq OWNED BY catalog.products.id;


--
-- Name: warehouses; Type: TABLE; Schema: catalog; Owner: app_user
--

CREATE TABLE catalog.warehouses (
    id integer NOT NULL,
    city character varying(100) NOT NULL,
    address character varying(255) NOT NULL,
    label character varying(255),
    is_central boolean DEFAULT false NOT NULL
);


ALTER TABLE catalog.warehouses OWNER TO app_user;

--
-- Name: warehouses_id_seq; Type: SEQUENCE; Schema: catalog; Owner: app_user
--

CREATE SEQUENCE catalog.warehouses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE catalog.warehouses_id_seq OWNER TO app_user;

--
-- Name: warehouses_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: app_user
--

ALTER SEQUENCE catalog.warehouses_id_seq OWNED BY catalog.warehouses.id;


--
-- Name: product_categories id; Type: DEFAULT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.product_categories ALTER COLUMN id SET DEFAULT nextval('catalog.product_categories_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.products ALTER COLUMN id SET DEFAULT nextval('catalog.products_id_seq'::regclass);


--
-- Name: warehouses id; Type: DEFAULT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.warehouses ALTER COLUMN id SET DEFAULT nextval('catalog.warehouses_id_seq'::regclass);


--
-- Name: product_categories product_categories_pkey; Type: CONSTRAINT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.product_categories
    ADD CONSTRAINT product_categories_pkey PRIMARY KEY (id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: warehouses warehouses_pkey; Type: CONSTRAINT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.warehouses
    ADD CONSTRAINT warehouses_pkey PRIMARY KEY (id);


--
-- Name: products fk_product_category; Type: FK CONSTRAINT; Schema: catalog; Owner: app_user
--

ALTER TABLE ONLY catalog.products
    ADD CONSTRAINT fk_product_category FOREIGN KEY (category_id) REFERENCES catalog.product_categories(id) ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict nNwjQFu6E5IxnU3lae6yfPhjZDTYRb4MYADBNiBdhY3Qzf4dmD8EAJ73ApRFEKO


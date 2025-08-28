-- sql/compat_fallback.sql

DO $$
BEGIN
  IF to_regclass('public.mv_active_listings') IS NULL THEN
    EXECUTE '
      CREATE MATERIALIZED VIEW mv_active_listings AS
      SELECT
        l.listing_id, l.property_id, l.source_id, l.tenure, l.status, l.price, l.price_units,
        l.bedrooms, l.bathrooms, l.sqft_interior, l.sqft_lot, l.url, l.refreshed_at, l.scraped_at,
        p.property_type,
        a.city, a.county, a.state_code, a.zip, a.latitude, a.longitude,
        p.zoning_code
      FROM listings l
      JOIN properties p ON p.property_id = l.property_id
      LEFT JOIN addresses a ON a.address_id = p.address_id
      WHERE l.status = ''active'';
    ';
  END IF;
END
$$;

DO $$
BEGIN
  IF to_regclass('public.v_place_latest_crime') IS NULL THEN
    IF to_regclass('public.crime_stats') IS NOT NULL THEN
      EXECUTE '
        CREATE VIEW v_place_latest_crime AS
        SELECT DISTINCT ON (place_id)
          place_id, period_start, period_end, violent_count, property_count, other_count,
          total_count, population, rate_per_1k, source_url
        FROM crime_stats
        ORDER BY place_id, period_end DESC;
      ';
    ELSE
      EXECUTE '
        CREATE VIEW v_place_latest_crime AS
        SELECT NULL::int AS place_id, NULL::date AS period_start, NULL::date AS period_end,
               NULL::int AS violent_count, NULL::int AS property_count, NULL::int AS other_count,
               NULL::int AS total_count, NULL::int AS population, NULL::numeric AS rate_per_1k,
               NULL::text AS source_url
        WHERE false;
      ';
    END IF;
  END IF;
END
$$;

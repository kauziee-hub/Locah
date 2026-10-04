from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    INET,
    JSONB,
    TSTZRANGE,
    TSVECTOR,
    UUID as PG_UUID,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class PlatformIdentity(Base):
    __tablename__ = "platform_identities"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    supabase_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaAsset(Base):
    """Uploaded media (Doc 12 §15.2). Domain rows store the asset id, never a
    provider URL — `public_url` here is the only place a storage URL lives."""

    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True
    )
    uploader_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bucket: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'media'"))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    # Provenance (website creative v4): who made this picture, for which slot,
    # and whether the owner has approved a draft LOCAH drew.
    source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'owner_uploaded'"))
    generated_for: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'approved'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsumerProfile(Base):
    __tablename__ = "consumer_profiles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), unique=True
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformAdminGrant(Base):
    __tablename__ = "platform_admin_grants"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    granted_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'in_good_standing'")
    )
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'private'"))
    primary_owner_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    business_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capability Universe §4.4 — the kind of business and how it is organised.
    category_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    subcategory_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_shape: Mapped[str | None] = mapped_column(Text, nullable=True)
    characteristics: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BusinessTrait(Base):
    """One operating trait of a Business (Capability Universe §4.3)."""

    __tablename__ = "business_traits"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    trait_key: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessModuleDismissal(Base):
    """A recommended tool the owner put off ("Not now"), with the reasons known then.

    It comes back only when a reason appears that is not in `evidence_keys`
    (catalog.recommendation_evidence.rank). `restored_at` set = brought back."""

    __tablename__ = "business_module_dismissals"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    module_id: Mapped[str] = mapped_column(Text, primary_key=True)
    evidence_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    dismissed_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=False
    )
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagline: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    cover_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    contact: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    social_links: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    completeness_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebsiteSectionType(Base):
    __tablename__ = "website_section_types"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    allowed_variants: Mapped[list[Any]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    contributing_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_module: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Website(Base):
    __tablename__ = "websites"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), unique=True, nullable=False
    )
    published_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    # P1-10C: module sections the owner chose not to show (see website.capabilities).
    auto_sections_hidden: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    # P1-10E6: 'en' | 'ta' | 'hi'; the first is what a visitor sees first.
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{en}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebsiteVersion(Base):
    __tablename__ = "website_versions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    website_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("websites.id"))
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    version_type: Mapped[str] = mapped_column(Text, nullable=False)
    navigation: Mapped[list[Any] | dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    generated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # AUD-08: set when a newer draft soft-replaces this one. Exactly one draft
    # row per website has superseded_at IS NULL (enforced by a partial unique
    # index) — that is "the current draft", no created_at ordering needed.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebsitePage(Base):
    __tablename__ = "website_pages"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    website_version_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("website_versions.id")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    page_type: Mapped[str] = mapped_column(Text, nullable=False)
    seo_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    seo_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebsiteSection(Base):
    __tablename__ = "website_sections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    page_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("website_pages.id"))
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    section_type_id: Mapped[str] = mapped_column(Text, ForeignKey("website_section_types.id"))
    layout_variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    module_binding: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebsiteGenerationJob(Base):
    __tablename__ = "website_generation_jobs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    ai_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'v1'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    intake: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    triggered_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    provider_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketplaceBusinessProjection(Base):
    __tablename__ = "marketplace_business_projections"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    characteristics: Mapped[list[Any]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    primary_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    primary_location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    is_discoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    logo_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    website_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    capability_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Discovery depth (20260924082800): placed by platform_core.business_categories
    # and read from what the Business published.
    category_family: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    locality: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    geo_precision: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[Any]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    highlights: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    offering_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    public_contact: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    site_paths: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # The verified average of every published review (Capability Universe §17.2).
    rating_average: Mapped[Any | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)


class MarketplaceOfferingProjection(Base):
    __tablename__ = "marketplace_offering_projections"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    offering_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_from: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    location_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)


class MarketplaceIndexHealth(Base):
    __tablename__ = "marketplace_index_health"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'never'"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discoverability_consented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consented_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessLocation(Base):
    __tablename__ = "business_locations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'UTC'"))
    hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # store | warehouse | van. A van is a stock location, not a second inventory.
    stock_role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'store'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    internal_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BusinessEmployee(Base):
    __tablename__ = "business_employees"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    membership_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_memberships.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    designation: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BusinessEmployeeLocationAssignment(Base):
    __tablename__ = "business_employee_location_assignments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_employees.id")
    )
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )


class CustomerContact(Base):
    __tablename__ = "customer_relationships_contacts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    preferred_location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    # P1-10E6: 'en' | 'ta' | 'hi' — set from what they write ('detected') or pick ('chosen').
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class CustomerSegment(Base):
    """A rule-built segment (P1-10E2): the rules only; members are worked out each time."""

    __tablename__ = "customer_relationships_segments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rules: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class CustomerNote(Base):
    __tablename__ = "customer_relationships_notes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class CustomerTimelineEntry(Base):
    __tablename__ = "customer_relationships_timeline_entries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id")
    )
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfferingCategory(Base):
    __tablename__ = "offerings_catalog_categories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_categories.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class Offering(Base):
    __tablename__ = "offerings_catalog_offerings"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    category_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_categories.id"), nullable=True
    )
    offering_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'product'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    price_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'fixed'"))
    price_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    unit_of_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'public'"))
    image_asset_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    # Capability Universe §6.1/§6.3: kind fields, choice groups, packs, units, tax code.
    hsn_sac: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    option_groups: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Pre-order rules (P1-10D2): needs a date or may take one, notice, cutoff,
    # ready times, festival window, daily limit, advance, cancel window.
    preorder: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # Formula pricing (P1-10D2b): a rate on the board × quantity + making + extras;
    # "last" holds the inputs today's price was worked out from.
    price_formula: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    sell_units: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    variant_options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    stock_unit: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'piece'"))
    # §15.1 stock depth (P1-10A): batches/expiry, serials/warranty, how it is bought.
    batch_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    serial_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    warranty_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_units: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class OfferingCatalogImport(Base):
    """One committed catalogue import (CSV / XLSX / an AI-read document). Items
    are created as drafts; the batch keeps which offerings it created or updated
    so the owner can review them and make them live."""

    __tablename__ = "offerings_catalog_imports"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    offering_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'")
    )
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfferingVariant(Base):
    __tablename__ = "offerings_catalog_variants"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    offering_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryRecord(Base):
    __tablename__ = "inventory_records"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    offering_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id")
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_variants.id"), nullable=True
    )
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    # Null means the business owns the stock. Set means a client's goods, which
    # must never be counted in the business's available quantity.
    owner_customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reorder_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_value_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    offering_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id")
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_variants.id"), nullable=True
    )
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    inventory_record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_records.id")
    )
    movement_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    value_delta_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    source_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryTransfer(Base):
    __tablename__ = "inventory_transfers"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    source_location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    destination_location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'requested'"))
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryTransferLine(Base):
    __tablename__ = "inventory_transfer_lines"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    transfer_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("inventory_transfers.id"))
    offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id"))
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    value_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    allocations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class InventoryFieldKey(Base):
    """Replay guard for transfer moves, job consumption, and client stock."""

    __tablename__ = "inventory_field_keys"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryJobUse(Base):
    """How much of an item a job took from one location, and how much came back unused."""

    __tablename__ = "inventory_job_uses"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    job_ref: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id"))
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    quantity_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    quantity_back: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    value_out_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    value_back_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    allocations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerAsset(Base):
    """One asset a customer owns: vehicle, device, AC unit, machine, pet, or policy."""

    __tablename__ = "customer_assets"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id")
    )
    asset_kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    traits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class SalesOrder(Base):
    __tablename__ = "orders_orders"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True
    )
    order_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)  # P2-01 stage engine: a step within status
    payment_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'cod'"))
    payment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    internal_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capability Universe §14: once the business has a tax profile, orders are
    # priced by the billing engine — its round-off line and what it decided.
    # Where it came from (Capability Universe §6.1): web, whatsapp, pos, phone, workspace, marketplace, chitbridge.
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dated pre-orders (P1-10D2): when it is wanted, the advance its items ask
    # for, and the terms the customer confirmed (never rewritten later).
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preorder: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    advance_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    preorder_terms: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    round_off: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    tax_basis: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class OrderLineItem(Base):
    __tablename__ = "orders_order_line_items"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("orders_orders.id")
    )
    offering_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id")
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_variants.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    line_subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    line_tax: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    line_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    quantity_deducted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Capability Universe §6.3: what was chosen (pack, cut, add-ons, a gift
    # amount) and how much stock the line takes in the offering's stock unit.
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    stock_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=lambda ctx: ctx.get_current_parameters()["quantity"]
    )
    serials: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    batch_allocations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderStatusHistory(Base):
    __tablename__ = "orders_order_status_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("orders_orders.id")
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderNote(Base):
    __tablename__ = "orders_order_notes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("orders_orders.id")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class FulfilmentSettings(Base):
    __tablename__ = "fulfilment_settings"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    delivery_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    delivery_fee_offering_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id"), nullable=True
    )
    # Paying on delivery / at pickup, for every channel (20260929110100).
    cod_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    first_order_cod_cap: Mapped[Any | None] = mapped_column(Numeric(12, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class FulfilmentZone(Base):
    __tablename__ = "fulfilment_zones"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'city'"))
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    postal_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    center_lng: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    radius_km: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    charge_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class FulfilmentJob(Base):
    __tablename__ = "fulfilment_jobs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("orders_orders.id"), unique=True
    )
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    zone_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("fulfilment_zones.id"), nullable=True
    )
    delivery_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    delivery_charge: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    tracking_token: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class WorkforceMember(Base):
    __tablename__ = "workforce_members"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    designation: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class WorkforceLocationAssignment(Base):
    __tablename__ = "workforce_location_assignments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    member_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id")
    )
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )


class WorkforceServiceAssociation(Base):
    __tablename__ = "workforce_service_associations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    member_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id")
    )
    offering_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("offerings_catalog_offerings.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )


class WorkforceAvailability(Base):
    __tablename__ = "workforce_availability"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    member_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id")
    )
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exception_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[Any] = mapped_column(Time, nullable=False)
    end_time: Mapped[Any] = mapped_column(Time, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingsPolicy(Base):
    __tablename__ = "bookings_policies"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    require_deposit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deposit_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deposit_percent: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    cancel_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("24")
    )
    # How long an unpaid online deposit keeps its slot (Founder §17).
    hold_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    waitlist_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    waitlist_offer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("60"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ConsumerActivityProjection(Base):
    __tablename__ = "consumer_activity_projections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Booking(Base):
    __tablename__ = "bookings_bookings"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True
    )
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    provider_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_number: Mapped[str] = mapped_column(Text, nullable=False)
    reservation_mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'cod'"))
    payment_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    deposit_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    deposit_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    # What the booking costs, fixed when it is made (P1-10D); null when the
    # service has no fixed price.
    total_amount: Mapped[Any | None] = mapped_column(Numeric(12, 2), nullable=True)
    management_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    management_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    internal_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # An unpaid online deposit's slot is kept until then, then released.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    series_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_series.id"), nullable=True
    )
    occurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A site visit's sales relationship lives in Leads; the booking only points at it.
    lead_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("leads_leads.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BookingSeries(Base):
    """Linked weekly occurrences. Each occurrence is an ordinary booking."""

    __tablename__ = "bookings_series"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    interval_weeks: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    provider_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BookingWaitlistEntry(Base):
    """A request for a full slot. Never a booking until the customer takes an offer."""

    __tablename__ = "bookings_waitlist_entries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    provider_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    reservation_mode: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    customer_contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id")
    )
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'waiting'"))
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_bookings.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BookingStatusHistory(Base):
    __tablename__ = "bookings_booking_status_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    booking_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_bookings.id")
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingResource(Base):
    """A bookable asset — a room, table, court, vehicle, or a pool of seats.

    Deliberately not a person. A workforce member has employment, skills and
    pay; the two meet only in an allocation, which is the thing that collides.
    """

    __tablename__ = "bookings_resources"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id")
    )
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    allocation_mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'exclusive'")
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    min_party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buffer_before_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    buffer_after_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    granularity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'slot'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    resource_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BookingAllocation(Base):
    """One claim on one subject for one interval — the only thing that collides.

    `occupies` is half-open and already includes the resource's buffers, so
    turnaround and the difference between nights and slots both fall out of
    range arithmetic rather than needing their own branches.
    """

    __tablename__ = "bookings_booking_allocations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'booking'"))
    booking_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_bookings.id", ondelete="CASCADE"), nullable=True
    )
    resource_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_resources.id"), nullable=True
    )
    provider_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_exclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    occupies: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingNote(Base):
    __tablename__ = "bookings_booking_notes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    booking_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("bookings_bookings.id")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class MerchantConnection(Base):
    __tablename__ = "payments_merchant_connections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'stub'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'not_connected'"))
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Fernet ciphertext of the owner's provider API credentials (Razorpay
    # {key_id, key_secret}). Never plaintext, never serialized to a client.
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PaymentAttempt(Base):
    __tablename__ = "payments_payment_attempts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    payment_method: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'stub'"))
    provider_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    refunded_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # P1-10D: the link it was paid through, what it was for, the customer's or
    # counter's reference (UTR, card slip), who confirmed it and when.
    request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payments_requests.id"), nullable=True
    )
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    attention: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PaymentRequest(Base):
    """A secure link for an amount against a real transaction (P1-10D)."""

    __tablename__ = "payments_requests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PaymentRefund(Base):
    __tablename__ = "payments_refunds"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    payment_attempt_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payments_payment_attempts.id")
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The same key on the same payment returns this refund instead of a second one.
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # recorded: the owner gave it back themselves; provider: LOCAH asked the provider.
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'recorded'"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PaymentWebhookReceipt(Base):
    __tablename__ = "payments_webhook_receipts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    payment_attempt_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payments_payment_attempts.id"), nullable=True
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'received'"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Applying the receipt is retried with backoff, then dead-lettered (never lost).
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("8"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessMembership(Base):
    __tablename__ = "business_memberships"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    location_scope: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    # Capability Universe §7.2: the role template (or "custom:<id>") and scope.
    role_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'business'"))
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class BusinessInvitation(Base):
    __tablename__ = "business_invitations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    invited_email: Mapped[str] = mapped_column(Text, nullable=False)
    invited_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    invited_role: Mapped[str] = mapped_column(Text, nullable=False)
    location_scope: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    role_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'business'"))
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    join_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_memberships.id"), nullable=True
    )
    last_resent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resend_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class MembershipPermissionGrant(Base):
    __tablename__ = "business_membership_permission_grants"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_memberships.id")
    )
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    location_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=True
    )
    granted_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MembershipPermissionDenial(Base):
    __tablename__ = "business_membership_permission_denials"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_memberships.id")
    )
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    denied_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    denied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MembershipAppliedTemplate(Base):
    __tablename__ = "business_membership_applied_templates"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    membership_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_memberships.id")
    )
    template_id: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    customized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class CommercialEntitlement(Base):
    __tablename__ = "commercial_entitlements"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quantity_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    granted_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModuleDefinition(Base):
    __tablename__ = "module_definitions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    module_class: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessModuleState(Base):
    __tablename__ = "business_module_states"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    module_id: Mapped[str] = mapped_column(Text, ForeignKey("module_definitions.id"))
    activation_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'not_enabled'")
    )
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PlatformOutboxEvent(Base):
    __tablename__ = "platform_outbox_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_version: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'1.0'"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    causation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leased_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Quote(Base):
    """A commercial proposal. Immutable once issued — see QuoteItem."""

    __tablename__ = "quotes_quotes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customer_relationships_contacts.id"),
        nullable=True,
    )
    quote_number: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    supersedes_quote_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id"), nullable=True
    )
    root_quote_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    discount_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    tax_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    charges_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    discount_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deposit_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    deposit_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    deposit_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'not_required'")
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    price_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversion_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    converted_to_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    converted_to_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class QuoteItem(Base):
    """One line, holding its own copy of what the customer was shown.

    Nothing here is derived from the offering at read time. A catalogue price
    change must not alter a quote that has already been sent.
    """

    __tablename__ = "quotes_quote_items"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    quote_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id", ondelete="CASCADE")
    )
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False, server_default=text("1"))
    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    tax_rate: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, server_default=text("0"))
    discount_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    discount_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    line_subtotal: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    line_discount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    line_tax: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    line_total: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    line_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'item'"))
    moq: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_breaks: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    boq_section: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_matrix: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    item_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteCharge(Base):
    """An itemised charge beside the lines — delivery, installation, a premium."""

    __tablename__ = "quotes_quote_charges"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    quote_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    tax_rate: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteSettings(Base):
    """The executive discount ceiling for one business. Owner approval sits above it."""

    __tablename__ = "quotes_settings"

    business_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True
    )
    executive_discount_limit_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("5")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotePaymentPlanLine(Base):
    """One stage of the plan offered with the quote. Payments collects it later."""

    __tablename__ = "quotes_payment_plan_lines"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    quote_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    amount_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount_value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    due_rule: Mapped[str] = mapped_column(Text, nullable=False)
    due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteView(Base):
    """One opening of one version by the customer holding the share link."""

    __tablename__ = "quotes_views"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    quote_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id", ondelete="CASCADE")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuoteRfqIntake(Base):
    """Idempotency for a website or WhatsApp request that became a draft quote."""

    __tablename__ = "quotes_rfq_intakes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    quote_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformEventDelivery(Base):
    """One subscriber's delivery of one outbox event.

    Delivery state lives here rather than on the event so that a subscriber can
    fail and retry without re-running the subscribers that already succeeded.
    """

    __tablename__ = "platform_event_deliveries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_outbox_events.id", ondelete="CASCADE")
    )
    subscriber_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    business_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leased_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    actor_context: Mapped[str] = mapped_column(Text, nullable=False)
    business_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ============================================================
# Stage 6 - Leads (module: leads)
# ============================================================
class Lead(Base):
    __tablename__ = "leads_leads"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    origin_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'new'"))
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)  # P2-01 stage engine: a step within status
    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    next_follow_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class LeadStatusHistory(Base):
    __tablename__ = "leads_lead_status_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("leads_leads.id"))
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeadNote(Base):
    __tablename__ = "leads_lead_notes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    lead_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("leads_leads.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


# ============================================================
# Stage 6 - Memberships (module: memberships)
# ============================================================
class MembershipPlan(Base):
    __tablename__ = "memberships_plans"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    price_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    billing_model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'fixed_duration'")
    )
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'private'"))
    # P2-02: what kind of recurring relationship this plan is, and its rules.
    plan_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'access'"))
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    grace_allows_entry: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    freeze_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    max_freeze_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sessions_included: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consume_on: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'completed'"))
    no_show_consumes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    delivery: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    billing_timing: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'prepaid'"))
    instalment_template: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    visits_included: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visit_every_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class MembershipPlanOfferingAccess(Base):
    __tablename__ = "memberships_plan_offering_access"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("memberships_plans.id")
    )
    offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MembershipEnrolment(Base):
    __tablename__ = "memberships_enrolments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("memberships_plans.id")
    )
    customer_contact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id")
    )
    identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    payment_attempt_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    payment_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    auto_renew: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # P2-02: where and by whom it is looked after, who pays, what it refers to
    # in another module, this subscriber's schedule, and cached answers.
    location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    responsible_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    source_ref_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    delivery: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    checkin_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class MembershipEnrolmentStatusHistory(Base):
    __tablename__ = "memberships_enrolment_status_history"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    enrolment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("memberships_enrolments.id")
    )
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Backward-compatible alias during transition
class PlatformNotification(Base):
    __tablename__ = "platform_notifications"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    recipient_identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    notification_type: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'operational'")
    )
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PlatformNotificationPreference(Base):
    __tablename__ = "platform_notification_preferences"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    identity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id")
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

class Project(Base):
    """A unit of committed work for a customer, steered to completion.

    One table for what different trades call a project, a job, a case or a work
    order: the difference between them is vocabulary and length, not structure.
    The noun and the starting phases come from the Business-Type Profile, so no
    vertical appears as a branch here.
    """

    __tablename__ = "projects_projects"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("business_locations.id"), nullable=True
    )
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customer_relationships_contacts.id"),
        nullable=True,
    )
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)  # P2-01 stage engine: a step within status
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'normal'"))
    starts_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    on_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_quote_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotes_quotes.id"), nullable=True
    )
    agreed_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    lead_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectPhase(Base):
    """A named stage of a project, ordered."""

    __tablename__ = "projects_phases"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects_projects.id")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    is_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    due_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responsible_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoicing_documents.id"), nullable=True
    )
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectTask(Base):
    """A piece of work inside a project, optionally within a phase.

    `assignee_member_id` points at the workforce module. A project does not keep
    its own idea of who works here.
    """

    __tablename__ = "projects_tasks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects_projects.id")
    )
    phase_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects_phases.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'todo'"))
    assignee_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workforce_members.id"), nullable=True
    )
    due_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- invoicing (P1-04)
def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class InvoicingTaxProfile(Base):
    """How the business bills (Capability Universe §14.4). Owner / CA data."""

    __tablename__ = "invoicing_tax_profiles"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False)
    round_off: Mapped[bool] = mapped_column(Boolean, nullable=False)
    issue_on: Mapped[str] = mapped_column(Text, nullable=False)
    advances_treatment: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ca_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicingRegistration(Base):
    """A GST registration (one per state), or the business's 'not registered' row."""

    __tablename__ = "invoicing_registrations"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    scheme: Mapped[str] = mapped_column(Text, nullable=False)
    gstin: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    trade_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_code: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    composition_declaration: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicingRegister(Base):
    """A billing counter at a location; its series is GSTIN × FY × register."""

    __tablename__ = "invoicing_registers"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    registration_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoicing_registrations.id"))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    pad: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicingTaxRate(Base):
    """A GST rate for an offering or an HSN/SAC code, effective over a date range."""

    __tablename__ = "invoicing_tax_rates"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    hsn_sac: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    effective_from: Mapped[Any] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Any | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicingDocument(Base):
    """Tax invoice, bill of supply, bill, credit note or debit note (§14.4)."""

    __tablename__ = "invoicing_documents"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    register_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoicing_registers.id"))
    registration_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoicing_registrations.id"))
    doc_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    series_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    fy: Mapped[str | None] = mapped_column(Text, nullable=True)
    seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    order_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("orders_orders.id"), nullable=True)
    original_document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    note_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    restock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    buyer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    seller: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    place_of_supply: Mapped[str | None] = mapped_column(Text, nullable=True)
    intra_state: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'INR'"))
    taxable_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    cgst_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    sgst_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    igst_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    tax_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    round_off: Mapped[Any] = mapped_column(Numeric(8, 2), nullable=False, server_default=text("0"))
    grand_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    amount_due: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    amount_paid: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Counter bills (P1-05): the shift and device they were rung up on, when.
    shift_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    device_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pos_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Sold on the customer's account (khata, P1-06): what is owed sits in their ledger.
    on_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InvoicingDocumentLine(Base):
    __tablename__ = "invoicing_document_lines"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoicing_documents.id", ondelete="CASCADE")
    )
    offering_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    order_line_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    original_line_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Any] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False)
    discount: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    taxable_value: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    tax_rate: Mapped[Any | None] = mapped_column(Numeric(5, 2), nullable=True)
    cgst: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    sgst: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    igst: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=False, server_default=text("0"))
    line_total: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    serials: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    batch_allocations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # What a formula-priced line was sold at: rate, quantity, making (P1-10D2b).
    price_basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoicingPayment(Base):
    __tablename__ = "invoicing_payments"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoicing_documents.id"))
    amount: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_on: Mapped[Any] = mapped_column(Date, nullable=False)
    recorded_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    shift_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    verification: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'verified'"))
    verified_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # P1-10D: 'khata' when applied from a khata receipt, 'payment_attempt' when a
    # payment link or recorded payment settled the bill — so money counts once.
    via: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_attempt_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- counter billing (P1-05)
class PosSettings(Base):
    """The owner's counter rules (Capability Universe §14.1–§14.3)."""

    __tablename__ = "pos_settings"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    upi_vpa: Mapped[str | None] = mapped_column(Text, nullable=True)
    upi_payee_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_window_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("7"))
    discount_caps: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    block_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("50"))
    weighed_label: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    receipt_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PosApprovalPin(Base):
    __tablename__ = "pos_approval_pins"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    identity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    pin_hash: Mapped[str] = mapped_column(Text, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PosShift(Base):
    """A cash-drawer shift on one register (§14.1, §14.5)."""

    __tablename__ = "pos_shifts"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    register_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("invoicing_registers.id"))
    device_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    opened_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    opening_cash: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    closed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_cash: Mapped[Any | None] = mapped_column(Numeric(14, 2), nullable=True)
    counted_cash: Mapped[Any | None] = mapped_column(Numeric(14, 2), nullable=True)
    variance: Mapped[Any | None] = mapped_column(Numeric(14, 2), nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PosCashMovement(Base):
    __tablename__ = "pos_cash_movements"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    shift_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pos_shifts.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    client_mutation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



# ---------------------------------------------------------------- khata / credit book (P1-06)
class LedgerAccount(Base):
    """A customer's or supplier's running account (Capability Universe §6.2, §14.5)."""

    __tablename__ = "ledger_accounts"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    party_type: Mapped[str] = mapped_column(Text, nullable=False)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    gstin: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False, server_default=text("0"))
    credit_limit: Mapped[Any | None] = mapped_column(Numeric(14, 2), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    public_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class LedgerEntry(Base):
    """One append-only line in an account; balance_after is the running balance."""

    __tablename__ = "ledger_entries"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ledger_accounts.id"))
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    balance_after: Mapped[Any] = mapped_column(Numeric(14, 2), nullable=False)
    entry_date: Mapped[Any] = mapped_column(Date, nullable=False)
    due_date: Mapped[Any | None] = mapped_column(Date, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    shift_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    over_limit_approved_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class MessagingChannel(Base):
    """A business's WhatsApp number (Capability Universe §9.1). One per business."""

    __tablename__ = "messaging_channels"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="whatsapp", server_default=text("'whatsapp'"))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default=text("'pending'"))
    display_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_number_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    waba_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    coexistence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    quality_rating: Mapped[str | None] = mapped_column(Text, nullable=True)
    messaging_limit: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # Meta requires the number to be registered for Cloud API (two-step PIN)
    # after Embedded Signup; until then it cannot send.
    phone_registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    calling_status: Mapped[str] = mapped_column(Text, nullable=False, default="off", server_default=text("'off'"))
    calling_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calling_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


class CallSession(Base):
    """One call - WhatsApp or phone - and what happened to it. No media or SDP."""

    __tablename__ = "calls_sessions"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    external_call_id: Mapped[str] = mapped_column(Text, nullable=False)
    from_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_contact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customer_relationships_contacts.id"), nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="ringing", server_default=text("'ringing'"))
    handled_by_type: Mapped[str] = mapped_column(Text, nullable=False, default="none", server_default=text("'none'"))
    handled_by_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    within_business_hours: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    handoffs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


class CallPermission(Base):
    """A customer's permission for this business to call them on WhatsApp."""

    __tablename__ = "calls_permissions"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    wa_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    is_permanent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requests: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessagingSettings(Base):
    __tablename__ = "messaging_settings"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en", server_default=text("'en'"))
    customer_updates: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                             server_default=text("'{}'::jsonb"))
    human_pause_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default=text("12"))
    cod_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    first_order_cod_cap: Mapped[Any | None] = mapped_column(Numeric(12, 2), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


class MessagingTemplate(Base):
    __tablename__ = "messaging_templates"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    template_key: Mapped[str] = mapped_column(Text, primary_key=True)
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="submitted", server_default=text("'submitted'"))
    provider_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The category Meta decided at approval (may differ from the one asked for).
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessagingConversation(Base):
    """One customer's WhatsApp thread with the business (Capability Universe §12.5)."""

    __tablename__ = "messaging_conversations"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    channel_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messaging_channels.id"))
    contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    wa_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="customer", server_default=text("'customer'"))
    profile_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="open", server_default=text("'open'"))
    handler: Mapped[str] = mapped_column(Text, nullable=False, default="bot", server_default=text("'bot'"))
    needs_person: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    unread: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_human_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    journey: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))


class MessagingMessage(Base):
    __tablename__ = "messaging_messages"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("messaging_conversations.id"))
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict,
                                                    server_default=text("'{}'::jsonb"))
    template_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_via: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("clock_timestamp()"))
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MessagingStaffAlert(Base):
    __tablename__ = "messaging_staff_alerts"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    identity_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"),
                                              primary_key=True)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    kinds: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list,
                                             server_default=text("'{}'"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    opted_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessagingQuickReply(Base):
    __tablename__ = "messaging_quick_replies"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

PlatformProfile = PlatformIdentity


class ReviewInvitation(Base):
    """One per completed interaction (Capability Universe §17.1); its link is the reviewer's credential."""

    __tablename__ = "reviews_invitations"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    customer_contact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    """A verified review. Never deleted; rating and text change only on the reviewer's path (§17.2)."""

    __tablename__ = "reviews_reviews"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    invitation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    customer_contact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reviewer_name: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'published'"))
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    featured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    removed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    appeal_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    appealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ReviewPhoto(Base):
    __tablename__ = "reviews_photos"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewReport(Base):
    __tablename__ = "reviews_reports"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewModerationLog(Base):
    __tablename__ = "reviews_moderation_log"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    review_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComplianceItem(Base):
    """A licence (expiry date) or a filing (next due date) — Capability Universe §6.2 `compliance`."""

    __tablename__ = "compliance_items"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    licence_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    due_on: Mapped[Any] = mapped_column(Date, nullable=False)
    recurrence: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_on_site: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    last_done_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ComplianceHistory(Base):
    __tablename__ = "compliance_history"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_due: Mapped[Any | None] = mapped_column(Date, nullable=True)
    to_due: Mapped[Any | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- P1-10A stock depth (§15.1)
class InventoryBatch(Base):
    __tablename__ = "inventory_batches"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    inventory_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    batch_code: Mapped[str] = mapped_column(Text, nullable=False)
    expires_on: Mapped[Any | None] = mapped_column(Date, nullable=True)
    received_on: Mapped[Any] = mapped_column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventorySerial(Base):
    __tablename__ = "inventory_serials"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    inventory_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    serial: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'in_stock'"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_document_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sold_order_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    warranty_until: Mapped[Any | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryYield(Base):
    __tablename__ = "inventory_yields"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    source_offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    output_offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    yield_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryConversion(Base):
    __tablename__ = "inventory_conversions"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_offering_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    outputs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    trim_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryCount(Base):
    __tablename__ = "inventory_counts"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    started_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    submitted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class InventoryCountLine(Base):
    __tablename__ = "inventory_count_lines"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    count_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    inventory_record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    expected_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PricingRate(Base):
    """A rate on the business's rate board (22K gold per gram, silver per gram)."""

    __tablename__ = "pricing_rates"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'g'"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PricingRateValue(Base):
    """One value an owner entered for a rate (append-only history)."""

    __tablename__ = "pricing_rate_values"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    rate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("pricing_rates.id"))
    value: Mapped[Any] = mapped_column(Numeric(14, 4), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- stage engine (P2-01, MD §24 #10)
class StageSet(Base):
    """A business's own steps inside a module's statuses (orders, leads, projects)."""

    __tablename__ = "platform_stage_sets"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StageEvent(Base):
    """One move of a record from one stage to another (history; never changed)."""

    __tablename__ = "platform_stage_events"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    from_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_stage: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------- walk-in queue (Guide §6.2 queue-operations)
class QueueLane(Base):
    """One live queue at a location, optionally for a provider, department, or resource."""

    __tablename__ = "queue_lanes"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    allow_requeue: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    turn_soon_ahead: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    avg_service_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    token_seq_day: Mapped[Any | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class QueueEntry(Base):
    """A walk-in token. booking_id is a reference; booking fields are not copied."""

    __tablename__ = "queue_entries"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("business_locations.id"))
    lane_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("queue_lanes.id"))
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    token_day: Mapped[Any] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'waiting'"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    booking_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    party_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    provider_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    visit_cycle: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    turn_soon_emitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    serving_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class QueueEntryEvent(Base):
    __tablename__ = "queue_entry_events"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    entry_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueueTurnNotice(Base):
    """One 'your turn soon' signal per token visit. Messaging consumes the event."""

    __tablename__ = "queue_turn_notices"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    entry_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    visit_cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    ahead: Mapped[int] = mapped_column(Integer, nullable=False)
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_contact_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    booking_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

# ---------------------------------------------------------------- shared tasks (Guide §6.2 tasks)
class WorkTask(Base):
    """One task. related_type / related_id point at the record it belongs to."""

    __tablename__ = "tasks_tasks"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'normal'"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_member_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    related_type: Mapped[str] = mapped_column(Text, nullable=False)
    related_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    occurrence_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class TaskChecklistItem(Base):
    __tablename__ = "tasks_checklist_items"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tasks_tasks.id"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    photo_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    proof_media_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskHistory(Base):
    __tablename__ = "tasks_history"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_identity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskChecklistTemplate(Base):
    __tablename__ = "tasks_checklist_templates"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    location_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'custom'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class TaskChecklistTemplateItem(Base):
    __tablename__ = "tasks_checklist_template_items"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tasks_checklist_templates.id")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    photo_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))



# ---------------------------------------------------------------- AI employees
# One shared runtime (platform_core/ai_employees). No tool writes these three
# tables: an AI employee cannot change its own tools, tier or limits.
class AIEmployee(Base):
    __tablename__ = "ai_employees"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    autonomy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'T1'"))
    tools: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AITestRecord(Base):
    """An order, booking or enquiry approved in AI Employee Test Mode — never a
    real one. No module reads this table (see the migration)."""

    __tablename__ = "ai_test_records"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'confirmed'"))
    payment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("platform_identities.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIEmployeeControl(Base):
    __tablename__ = "ai_employee_controls"

    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIAction(Base):
    __tablename__ = "ai_actions"

    id: Mapped[UUID] = _uuid_pk()
    business_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("businesses.id"))
    ai_employee_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_employees.id"))
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    related_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    approval_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    conversation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

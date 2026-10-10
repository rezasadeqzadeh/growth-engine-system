"""competitor pages read from Meta

Revision ID: 3b7c1e9a5d20
Revises: fc1fde2d045a
Create Date: 2026-10-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3b7c1e9a5d20'
down_revision: Union[str, Sequence[str], None] = 'fc1fde2d045a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('competitors') as t:
        t.add_column(sa.Column('ig_id', sa.String(length=40), nullable=True))
        t.add_column(sa.Column('biography', sa.Text(), nullable=False, server_default=''))
        t.add_column(sa.Column('website', sa.String(length=300), nullable=True))
        t.add_column(sa.Column('profile_picture_url', sa.Text(), nullable=True))
        t.add_column(sa.Column('media_count', sa.Integer(), nullable=True))
        t.add_column(sa.Column('fetch_status', sa.String(length=20), nullable=False, server_default='idle'))
        t.add_column(sa.Column('fetch_error', sa.String(length=500), nullable=True))
        t.add_column(sa.Column('insight', sa.JSON(), nullable=True))
    with op.batch_alter_table('competitor_posts') as t:
        t.add_column(sa.Column('external_id', sa.String(length=40), nullable=True))
        t.add_column(sa.Column('media_url', sa.Text(), nullable=True))
        t.add_column(sa.Column('content_type', sa.String(length=40), nullable=True))
        t.add_column(sa.Column('topic', sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('competitor_posts') as t:
        for name in ('topic', 'content_type', 'media_url', 'external_id'):
            t.drop_column(name)
    with op.batch_alter_table('competitors') as t:
        for name in ('insight', 'fetch_error', 'fetch_status', 'media_count', 'profile_picture_url', 'website',
                     'biography', 'ig_id'):
            t.drop_column(name)

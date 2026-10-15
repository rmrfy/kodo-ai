"""Workspace provisioning and access helpers shared by auth and APIs."""
from sqlalchemy import select

from ..models import Organization, OrganizationMembership, User, Workspace


def ensure_personal_workspace(db, user: User) -> Workspace:
    # Serialize first-time provisioning for the same account. The unique
    # constraint remains the final guard if a caller bypasses this helper.
    if user.id:
        db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    workspace = db.scalar(select(Workspace).where(
        Workspace.kind == "personal", Workspace.owner_user_id == user.id,
    ))
    if workspace:
        return workspace
    workspace = Workspace(kind="personal", name="Personal workspace", owner_user_id=user.id)
    db.add(workspace)
    db.flush()
    return workspace


def create_organization_workspace(db, user: User, name: str) -> tuple[Workspace, Organization]:
    workspace = Workspace(kind="organization", name=name)
    db.add(workspace)
    db.flush()
    organization = Organization(name=name, created_by_user_id=user.id, workspace_id=workspace.id)
    db.add(organization)
    db.flush()
    return workspace, organization


def workspace_for_organization(db, organization_id: str) -> Workspace | None:
    return db.scalar(select(Workspace).join(
        Organization, Organization.workspace_id == Workspace.id,
    ).where(Organization.id == organization_id, Workspace.kind == "organization"))


def user_can_access_workspace(db, user_id: str, workspace: Workspace) -> bool:
    if workspace.kind == "personal":
        return workspace.owner_user_id == user_id
    organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id))
    if not organization:
        return False
    return db.scalar(select(OrganizationMembership.id).where(
        OrganizationMembership.organization_id == organization.id,
        OrganizationMembership.user_id == user_id,
    )) is not None


def user_can_manage_workspace(db, user_id: str, workspace: Workspace) -> bool:
    if workspace.kind == "personal":
        return workspace.owner_user_id == user_id
    organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id))
    if not organization:
        return False
    role = db.scalar(select(OrganizationMembership.role).where(
        OrganizationMembership.organization_id == organization.id,
        OrganizationMembership.user_id == user_id,
    ))
    return role in {"owner", "admin"}

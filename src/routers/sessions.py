import logging

from fastapi import APIRouter, Body, Depends, Path, Query, Response
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from src import config, crud, schemas
from src.dependencies import db
from src.exceptions import (
    AuthenticationException,
    ResourceNotFoundException,
    ValidationException,
)
from src.security import JWTParams, require_auth
from src.utils import summarizer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/sessions",
    tags=["sessions"],
)


@router.post(
    "",
    response_model=schemas.Session,
)
async def get_or_create_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session: schemas.SessionCreate = Body(
        ..., description="Session creation parameters"
    ),
    jwt_params: JWTParams = Depends(require_auth()),
    db: AsyncSession = db,
):
    """
    Get a specific session in a workspace.

    If session_id is provided as a query parameter, it verifies the session is in the workspace.
    Otherwise, it uses the session_id from the JWT token for verification.
    """
    # Verify JWT has access to the requested resource
    if not jwt_params.ad and jwt_params.w is not None and jwt_params.w != workspace_id:
        raise AuthenticationException("Unauthorized access to resource")

    # Use session from JWT if not provided in query
    if session.name:
        if (
            not jwt_params.ad
            and jwt_params.s is not None
            and jwt_params.s != session.name
        ):
            raise AuthenticationException("Unauthorized access to resource")
    else:
        if not jwt_params.s:
            raise AuthenticationException(
                "Session ID not found in query parameter or JWT"
            )
        session.name = jwt_params.s

    # Handle session creation with proper error handling
    try:
        return await crud.get_or_create_session(
            db, workspace_name=workspace_id, session=session
        )
    except ValueError as e:
        logger.warning(f"Failed to get or create session {session.name}: {str(e)}")
        raise ValidationException(str(e)) from e


@router.post(
    "/list",
    response_model=Page[schemas.Session],
    dependencies=[Depends(require_auth(workspace_name="workspace_id"))],
)
async def get_sessions(
    workspace_id: str = Path(..., description="ID of the workspace"),
    options: schemas.SessionGet | None = Body(
        None, description="Filtering and pagination options for the sessions list"
    ),
    db: AsyncSession = db,
):
    """Get All Sessions in a Workspace"""
    filter_param = None

    if options and hasattr(options, "filter") and options.filter:
        filter_param = options.filter
        if filter_param == {}:  # Explicitly check for empty dict
            filter_param = None

    return await apaginate(
        db, await crud.get_sessions(workspace_name=workspace_id, filters=filter_param)
    )


@router.put(
    "/{session_id}",
    response_model=schemas.Session,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def update_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session to update"),
    session: schemas.SessionUpdate = Body(
        ..., description="Updated session parameters"
    ),
    db: AsyncSession = db,
):
    """Update the metadata of a Session"""
    try:
        updated_session = await crud.update_session(
            db, workspace_name=workspace_id, session_name=session_id, session=session
        )
        logger.info(f"Session {session_id} updated successfully")
        return updated_session
    except ValueError as e:
        logger.warning(f"Failed to update session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.delete(
    "/{session_id}",
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def delete_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session to delete"),
    db: AsyncSession = db,
):
    """Delete a session by marking it as inactive"""
    try:
        await crud.delete_session(
            db, workspace_name=workspace_id, session_name=session_id
        )
        logger.info(f"Session {session_id} deleted successfully")
        return {"message": "Session deleted successfully"}
    except ValueError as e:
        logger.warning(f"Failed to delete session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.get(
    "/{session_id}/clone",
    response_model=schemas.Session,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def clone_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session to clone"),
    db: AsyncSession = db,
    message_id: str | None = Query(
        None, description="Message ID to cut off the clone at"
    ),
):
    """Clone a session, optionally up to a specific message"""
    try:
        # TODO: Update crud.clone_session to work with new paradigm
        cloned_session = await crud.clone_session(
            db,
            workspace_name=workspace_id,
            original_session_name=session_id,
            cutoff_message_id=message_id,
        )
        logger.info(f"Session {session_id} cloned successfully")
        return cloned_session
    except ValueError as e:
        logger.warning(f"Failed to clone session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.post(
    "/{session_id}/peers",
    response_model=schemas.Session,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def add_peers_to_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    peers: dict[str, schemas.SessionPeerConfig] = Body(
        ..., description="List of peer IDs to add to the session"
    ),
    db: AsyncSession = db,
):
    """Add peers to a session"""
    try:
        session = await crud.get_or_create_session(
            db,
            session=schemas.SessionCreate(
                name=session_id,
                peers=peers,
            ),
            workspace_name=workspace_id,
        )
        logger.info(f"Added peers to session {session_id} successfully")
        return session
    except ValueError as e:
        logger.warning(f"Failed to add peers to session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.put(
    "/{session_id}/peers",
    response_model=schemas.Session,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def set_session_peers(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    peers: dict[str, schemas.SessionPeerConfig] = Body(
        ..., description="List of peer IDs to set for the session"
    ),
    db: AsyncSession = db,
):
    """Set the peers in a session"""
    try:
        await crud.set_peers_for_session(
            db,
            workspace_name=workspace_id,
            session_name=session_id,
            peer_names=peers,
        )
        # Get the session to return
        session = await crud.get_or_create_session(
            db,
            session=schemas.SessionCreate(name=session_id),
            workspace_name=workspace_id,
        )
        logger.info(f"Set peers for session {session_id} successfully")
        return session
    except ValueError as e:
        logger.warning(f"Failed to set peers for session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Failed to set peers for session") from e


@router.delete(
    "/{session_id}/peers",
    response_model=schemas.Session,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def remove_peers_from_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    peers: list[str] = Body(
        ..., description="List of peer IDs to remove from the session"
    ),
    db: AsyncSession = db,
):
    """Remove peers from a session"""
    try:
        await crud.remove_peers_from_session(
            db,
            workspace_name=workspace_id,
            session_name=session_id,
            peer_names=set(peers),
        )
        # Get the session to return
        session = await crud.get_or_create_session(
            db,
            session=schemas.SessionCreate(name=session_id),
            workspace_name=workspace_id,
        )
        logger.info(f"Removed peers from session {session_id} successfully")
        return session
    except ValueError as e:
        logger.warning(f"Failed to remove peers from session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.get(
    "/{session_id}/peers/{peer_id}/config",
    response_model=schemas.SessionPeerConfig,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def get_peer_config(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    peer_id: str = Path(..., description="ID of the peer"),
    db: AsyncSession = db,
):
    """Get the configuration for a peer in a session"""
    return await crud.get_peer_config(
        db,
        workspace_name=workspace_id,
        session_name=session_id,
        peer_id=peer_id,
    )


@router.post(
    "/{session_id}/peers/{peer_id}/config",
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def set_peer_config(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    peer_id: str = Path(..., description="ID of the peer"),
    config: schemas.SessionPeerConfig = Body(..., description="Peer configuration"),
    db: AsyncSession = db,
):
    """Set the configuration for a peer in a session"""
    try:
        await crud.set_peer_config(
            db,
            workspace_name=workspace_id,
            session_name=session_id,
            peer_name=peer_id,
            config=config,
        )
        logger.info(
            f"Set peer config for {peer_id} in session {session_id} successfully"
        )
        return Response(status_code=200)
    except ValueError as e:
        logger.warning(
            f"Failed to set peer config for {peer_id} in session {session_id}: {str(e)}"
        )
        raise ResourceNotFoundException("Session not found") from e


@router.get(
    "/{session_id}/peers",
    response_model=Page[schemas.Peer],
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def get_session_peers(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    db: AsyncSession = db,
):
    """Get peers from a session"""
    try:
        peers_query = await crud.get_peers_from_session(
            workspace_name=workspace_id, session_name=session_id
        )
        return await apaginate(db, peers_query)
    except ValueError as e:
        logger.warning(f"Failed to get peers from session {session_id}: {str(e)}")
        raise ResourceNotFoundException("Session not found") from e


@router.get(
    "/{session_id}/context",
    response_model=schemas.SessionContext,
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def get_session_context(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    tokens: int | None = Query(
        None,
        description="Number of tokens to use for the context. Includes summary if set to true",
    ),
    summary: bool = Query(
        True,
        description="Whether or not to include a summary *if* one is available for the session",
    ),
    force_new: bool = Query(
        False,
        description="Whether or not the included summary should be generated on-the-fly in order to exhaustively cover the session history. The summary flag must be true for this to take effect.",
    ),
    db: AsyncSession = db,
):
    """
    Produce a context object from the session. The caller provides a token limit which the entire context must fit into.
    To do this, we allocate 40% of the token limit to the summary, and 60% to recent messages -- as many as can fit.
    If the caller does not want a summary, we allocate all the tokens to recent messages.
    The default token limit if not provided is 2048.
    """
    token_limit = tokens or config.settings.GET_CONTEXT_DEFAULT_MAX_TOKENS

    summary_content = ""
    messages_tokens = token_limit

    if summary:
        if force_new:
            logger.warning("Exhaustive summary requested -- not currently available")

        summary_tokens_limit = token_limit * 0.4

        latest_long_summary, latest_short_summary = await summarizer.get_both_summaries(
            db,
            workspace_name=workspace_id,
            session_name=session_id,
        )

        long_len = latest_long_summary["token_count"] if latest_long_summary else 0
        short_len = latest_short_summary["token_count"] if latest_short_summary else 0

        # The goal is to return the longest summary that fits within the token limit
        # Sometimes (rarely) the short summary can be longer than the long summary,
        # so we need to check for that and return the longer one.

        if (
            latest_long_summary
            and latest_long_summary["token_count"] <= summary_tokens_limit
            and long_len > short_len
        ):
            summary_content = latest_long_summary["content"]
            messages_tokens = token_limit - latest_long_summary["token_count"]
        elif (
            latest_short_summary
            and latest_short_summary["token_count"] <= summary_tokens_limit
            and short_len > 0
        ):
            summary_content = latest_short_summary["content"]
            messages_tokens = token_limit - latest_short_summary["token_count"]
        else:
            logger.warning(
                "No summary available for get_context, returning empty string. long_summary_len: %s, short_summary_len: %s",
                long_len,
                short_len,
            )
            summary_content = ""

    # Get the recent messages to return verbatim
    messages_stmt = await crud.get_messages(
        workspace_name=workspace_id,
        session_name=session_id,
        token_limit=messages_tokens,
    )
    result = await db.execute(messages_stmt)
    messages = list(result.scalars().all())

    logger.info(f"Retrieved {len(messages)} recent messages for verbatim return")

    return schemas.SessionContext(
        name=session_id,
        messages=messages,  # pyright: ignore -- db message type and schema message type are different, but excess gets removed by schema
        summary=summary_content,
    )


@router.post(
    "/{session_id}/search",
    response_model=Page[schemas.Message],
    dependencies=[
        Depends(require_auth(workspace_name="workspace_id", session_name="session_id"))
    ],
)
async def search_session(
    workspace_id: str = Path(..., description="ID of the workspace"),
    session_id: str = Path(..., description="ID of the session"),
    search: schemas.MessageSearchOptions = Body(
        ..., description="Message search parameters "
    ),
    db: AsyncSession = db,
):
    """Search a Session"""
    query, semantic = search.query, search.semantic

    stmt = await crud.search(
        query,
        workspace_name=workspace_id,
        session_name=session_id,
        semantic=semantic,
    )

    return await apaginate(db, stmt)

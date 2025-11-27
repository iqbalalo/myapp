"""
Database CRUD Operations Router
Provides comprehensive REST API endpoints for PostgreSQL database operations
including CREATE, READ, UPDATE, DELETE operations with advanced features.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import hashlib
from datetime import datetime, date
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/db", tags=["Database Operations"])

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": os.getenv("DB_PORT", "5432"),
    "database": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "Pass#0123456789"),
}


# ============================================================================
# Pydantic Models for Request/Response
# ============================================================================


class ReadRequest(BaseModel):
    """Request model for READ operations"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    filters: Optional[Dict[str, Any]] = Field(
        default={}, description="Filter conditions"
    )
    limit: Optional[int] = Field(
        default=100, ge=1, le=10000, description="Max records to return"
    )
    offset: Optional[int] = Field(
        default=0, ge=0, description="Number of records to skip"
    )
    include_fields: Optional[List[str]] = Field(
        default=None, description="Specific fields to include"
    )
    exclude_fields: Optional[List[str]] = Field(
        default=None, description="Fields to exclude"
    )
    sort_by: Optional[str] = Field(default=None, description="Column name to sort by")
    sort_dir: Optional[str] = Field(
        default="ASC", pattern="^(ASC|DESC|asc|desc)$", description="Sort direction"
    )


class CreateRequest(BaseModel):
    """Request model for CREATE operations"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    data: Union[Dict[str, Any], List[Dict[str, Any]]] = Field(
        ..., description="Data to insert (single record or list)"
    )
    hash_password: Optional[bool] = Field(
        default=False, description="Whether to hash password field"
    )
    salt_field: Optional[str] = Field(
        default="email",
        description="Field to use as salt for password hashing (email or phone)",
    )


class UpdateRequest(BaseModel):
    """Request model for UPDATE operations"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    filters: Dict[str, Any] = Field(
        ..., description="Filter conditions to identify records to update"
    )
    data: Dict[str, Any] = Field(..., description="Data to update")
    hash_password: Optional[bool] = Field(
        default=False, description="Whether to hash password field"
    )
    salt_field: Optional[str] = Field(
        default="email", description="Field to use as salt for password hashing"
    )


class DeleteRequest(BaseModel):
    """Request model for DELETE operations"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    filters: Dict[str, Any] = Field(
        ..., description="Filter conditions to identify records to delete"
    )


class JoinReadRequest(BaseModel):
    """Request model for multi-table JOIN operations"""

    schema_name: str = Field(..., description="Database schema name")
    base_table: str = Field(..., description="Base table name")
    joins: List[Dict[str, Any]] = Field(..., description="List of join configurations")
    filters: Optional[Dict[str, Any]] = Field(
        default={}, description="Filter conditions"
    )
    select_fields: Optional[List[str]] = Field(
        default=None, description="Specific fields to select (use table.column format)"
    )
    limit: Optional[int] = Field(default=100, ge=1, le=10000)
    offset: Optional[int] = Field(default=0, ge=0)
    sort_by: Optional[str] = Field(
        default=None, description="Column to sort by (use table.column format)"
    )
    sort_dir: Optional[str] = Field(default="ASC", pattern="^(ASC|DESC|asc|desc)$")


class RawQueryRequest(BaseModel):
    """Request model for raw SQL queries"""

    schema_name: str = Field(..., description="Database schema name")
    query: str = Field(..., description="SQL query to execute")
    params: Optional[List[Any]] = Field(
        default=None, description="Query parameters for prepared statements"
    )
    read_only: Optional[bool] = Field(
        default=True, description="Whether query is read-only (SELECT)"
    )


class PasswordVerifyRequest(BaseModel):
    """Request model for password verification"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    identifier_field: str = Field(
        ..., description="Field to identify user (email or phone)"
    )
    identifier_value: str = Field(..., description="Value of identifier field")
    password: str = Field(..., description="Password to verify")
    salt_field: Optional[str] = Field(
        default=None, description="Field used as salt (defaults to identifier_field)"
    )


class BulkOperationRequest(BaseModel):
    """Request model for bulk operations"""

    schema_name: str = Field(..., description="Database schema name")
    table_name: str = Field(..., description="Table name")
    operation: str = Field(
        ..., pattern="^(create|update|delete)$", description="Operation type"
    )
    records: List[Dict[str, Any]] = Field(..., description="List of records to process")
    hash_password: Optional[bool] = Field(
        default=False, description="Whether to hash password field"
    )


# ============================================================================
# Helper Functions
# ============================================================================


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""

    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def get_db_connection():
    """Establishes database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Database connection failed: {str(e)}"
        )


def hash_password(password: str, salt: str) -> str:
    """Hash password with salt using SHA256"""
    if not password or not salt:
        raise ValueError("Password and salt are required for hashing")
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def encrypt_password_in_data(
    data: Dict[str, Any], salt_field: str = "email"
) -> Dict[str, Any]:
    """Encrypt password field in data dictionary"""
    if "password" in data and data["password"]:
        if salt_field not in data or not data[salt_field]:
            raise ValueError(
                f"Salt field '{salt_field}' is required for password hashing"
            )
        data["password"] = hash_password(data["password"], str(data[salt_field]))
    return data


def build_where_clause(filters: Dict[str, Any]) -> tuple:
    """Build WHERE clause from filters"""
    if not filters:
        return "", []

    where_parts = []
    values = []

    for key, value in filters.items():
        if value is None:
            where_parts.append(f'"{key}" IS NULL')
        elif isinstance(value, dict):
            # Support for operators like {"$gt": 100, "$lt": 200}
            for op, val in value.items():
                if op == "$gt":
                    where_parts.append(f'"{key}" > %s')
                    values.append(val)
                elif op == "$gte":
                    where_parts.append(f'"{key}" >= %s')
                    values.append(val)
                elif op == "$lt":
                    where_parts.append(f'"{key}" < %s')
                    values.append(val)
                elif op == "$lte":
                    where_parts.append(f'"{key}" <= %s')
                    values.append(val)
                elif op == "$ne":
                    where_parts.append(f'"{key}" != %s')
                    values.append(val)
                elif op == "$like":
                    where_parts.append(f'"{key}" LIKE %s')
                    values.append(val)
                elif op == "$ilike":
                    where_parts.append(f'"{key}" ILIKE %s')
                    values.append(val)
        elif isinstance(value, (list, tuple)):
            placeholders = ", ".join(["%s"] * len(value))
            where_parts.append(f'"{key}" IN ({placeholders})')
            values.extend(value)
        else:
            where_parts.append(f'"{key}" = %s')
            values.append(value)

    return " WHERE " + " AND ".join(where_parts), values


def serialize_json_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize dict/list values to JSON strings"""
    result = {}
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            result[key] = json.dumps(value)
        else:
            result[key] = value
    return result


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("/read")
async def read_records(request: ReadRequest):
    """
    Read records from a table with filtering, pagination, and field selection.

    Supports:
    - Filtering with operators ($gt, $lt, $gte, $lte, $ne, $like, $ilike)
    - Pagination (limit, offset)
    - Field selection (include_fields, exclude_fields)
    - Sorting (sort_by, sort_dir)

    Example filter with operators:
    ```json
    {
        "filters": {
            "age": {"$gte": 18, "$lt": 65},
            "name": {"$ilike": "%john%"},
            "status": ["active", "pending"]
        }
    }
    ```
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'

        # Build WHERE clause
        where_clause, where_values = build_where_clause(request.filters)

        # Build SELECT clause
        select_clause = "*"
        all_columns = None

        if request.include_fields or request.exclude_fields:
            # Get all columns
            temp_query = f"SELECT * FROM {full_table_name} LIMIT 0"
            cursor.execute(temp_query)
            all_columns = [desc[0] for desc in cursor.description]

            if request.include_fields:
                final_columns = [
                    col for col in request.include_fields if col in all_columns
                ]
                select_clause = ", ".join([f'"{c}"' for c in final_columns])
            elif request.exclude_fields:
                excluded_set = set(request.exclude_fields)
                final_columns = [col for col in all_columns if col not in excluded_set]
                select_clause = ", ".join([f'"{c}"' for c in final_columns])

        # Build ORDER BY clause
        order_by_clause = ""
        if request.sort_by:
            order_by_clause = (
                f' ORDER BY "{request.sort_by}" {request.sort_dir.upper()}'
            )

        # Build pagination
        pagination_clause = f" LIMIT {request.limit} OFFSET {request.offset}"

        # Execute query
        query = (
            f"SELECT {select_clause} FROM {full_table_name}"
            + where_clause
            + order_by_clause
            + pagination_clause
        )

        cursor.execute(query, where_values)
        results = cursor.fetchall()

        # Convert to list of dicts
        records = [dict(row) for row in results]

        cursor.close()
        conn.close()

        return {"success": True, "count": len(records), "data": records}

    except Exception as e:
        logger.error(f"Error in read_records: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_records(request: CreateRequest):
    """
    Create one or more records in a table.

    Supports:
    - Single record or bulk insert
    - Automatic password hashing
    - JSON field serialization
    - Returns created records
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'

        # Normalize data to list
        records = request.data if isinstance(request.data, list) else [request.data]

        # Process each record
        processed_records = []
        for record in records:
            # Hash password if requested
            if request.hash_password:
                record = encrypt_password_in_data(record, request.salt_field)

            # Serialize JSON fields
            record = serialize_json_fields(record)
            processed_records.append(record)

        if not processed_records:
            raise HTTPException(status_code=400, detail="No valid data to create")

        # Build INSERT query
        columns = list(processed_records[0].keys())
        columns_str = ", ".join([f'"{c}"' for c in columns])
        placeholders = ", ".join(["%s"] * len(columns))

        query = f"INSERT INTO {full_table_name} ({columns_str}) VALUES ({placeholders}) RETURNING *"

        created_records = []

        if len(processed_records) == 1:
            # Single insert
            values = [processed_records[0][col] for col in columns]
            cursor.execute(query, values)
            result = cursor.fetchone()
            created_records.append(dict(result))
        else:
            # Bulk insert
            for record in processed_records:
                values = [record[col] for col in columns]
                cursor.execute(query, values)
                result = cursor.fetchone()
                created_records.append(dict(result))

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "count": len(created_records),
            "data": created_records if len(created_records) > 1 else created_records[0],
        }

    except Exception as e:
        logger.error(f"Error in create_records: {e}")
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update")
async def update_records(request: UpdateRequest):
    """
    Update records in a table based on filter conditions.

    Supports:
    - Filter-based updates
    - Automatic password hashing
    - JSON field serialization
    - Returns updated records (up to 100)
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'

        # Process update data
        update_data = request.data.copy()

        # Hash password if requested
        if request.hash_password and "password" in update_data:
            # For updates, we need to get the salt value first
            where_clause, where_values = build_where_clause(request.filters)
            salt_query = (
                f'SELECT "{request.salt_field}" FROM {full_table_name}'
                + where_clause
                + " LIMIT 1"
            )
            cursor.execute(salt_query, where_values)
            salt_record = cursor.fetchone()

            if salt_record:
                salt_value = salt_record[request.salt_field]
                update_data["password"] = hash_password(
                    update_data["password"], str(salt_value)
                )

        # Serialize JSON fields
        update_data = serialize_json_fields(update_data)

        # Build UPDATE query
        set_parts = [f'"{key}" = %s' for key in update_data.keys()]
        set_clause = " SET " + ", ".join(set_parts)

        where_clause, where_values = build_where_clause(request.filters)

        query = f"UPDATE {full_table_name}" + set_clause + where_clause + " RETURNING *"
        values = list(update_data.values()) + where_values

        cursor.execute(query, values)
        updated_records = cursor.fetchall()

        num_updated = len(updated_records)

        conn.commit()
        cursor.close()
        conn.close()

        if num_updated == 0:
            return {
                "success": True,
                "count": 0,
                "message": "No records matched the filter criteria",
            }

        # Return individual records if <= 100, otherwise just count
        if num_updated <= 100:
            return {
                "success": True,
                "count": num_updated,
                "data": [dict(row) for row in updated_records],
            }
        else:
            return {
                "success": True,
                "count": num_updated,
                "message": f"{num_updated} records updated (too many to return individually)",
            }

    except Exception as e:
        logger.error(f"Error in update_records: {e}")
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete")
async def delete_records(request: DeleteRequest):
    """
    Delete records from a table based on filter conditions.

    Returns count of deleted records.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'

        where_clause, where_values = build_where_clause(request.filters)

        if not where_clause:
            raise HTTPException(
                status_code=400,
                detail="Delete operation requires filter conditions to prevent accidental deletion of all records",
            )

        query = f"DELETE FROM {full_table_name}" + where_clause + " RETURNING *"

        cursor.execute(query, where_values)
        deleted_records = cursor.fetchall()

        num_deleted = len(deleted_records)

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "count": num_deleted,
            "message": f"{num_deleted} record(s) deleted",
        }

    except Exception as e:
        logger.error(f"Error in delete_records: {e}")
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/join-read")
async def join_read(request: JoinReadRequest):
    """
    Perform multi-table JOIN queries.

    Join configuration format:
    ```json
    {
        "joins": [
            {
                "table": "orders",
                "type": "LEFT",  // INNER, LEFT, RIGHT, FULL
                "on": "users.id = orders.user_id"
            },
            {
                "table": "products",
                "type": "INNER",
                "on": "orders.product_id = products.id"
            }
        ]
    }
    ```
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Build SELECT clause
        select_clause = "*"
        if request.select_fields:
            select_clause = ", ".join(request.select_fields)

        # Build JOIN clause
        base_table = f'"{request.schema_name}"."{request.base_table}"'
        join_clause = ""

        for join in request.joins:
            join_type = join.get("type", "INNER").upper()
            join_table = f'"{request.schema_name}"."{join["table"]}"'
            join_on = join["on"]
            join_clause += f" {join_type} JOIN {join_table} ON {join_on}"

        # Build WHERE clause
        where_clause, where_values = build_where_clause(request.filters)

        # Build ORDER BY clause
        order_by_clause = ""
        if request.sort_by:
            order_by_clause = f" ORDER BY {request.sort_by} {request.sort_dir.upper()}"

        # Build pagination
        pagination_clause = f" LIMIT {request.limit} OFFSET {request.offset}"

        # Execute query
        query = (
            f"SELECT {select_clause} FROM {base_table}"
            + join_clause
            + where_clause
            + order_by_clause
            + pagination_clause
        )

        cursor.execute(query, where_values)
        results = cursor.fetchall()

        records = [dict(row) for row in results]

        cursor.close()
        conn.close()

        return {"success": True, "count": len(records), "data": records}

    except Exception as e:
        logger.error(f"Error in join_read: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/raw-query")
async def execute_raw_query(request: RawQueryRequest):
    """
    Execute a raw SQL query.

    WARNING: Use with caution. Ensure proper input validation.
    Set read_only=False for INSERT/UPDATE/DELETE operations.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Set search path to schema
        cursor.execute(f'SET search_path TO "{request.schema_name}"')

        # Execute query
        if request.params:
            cursor.execute(request.query, request.params)
        else:
            cursor.execute(request.query)

        # Handle different query types
        if request.read_only or request.query.strip().upper().startswith("SELECT"):
            results = cursor.fetchall()
            records = [dict(row) for row in results]

            cursor.close()
            conn.close()

            return {"success": True, "count": len(records), "data": records}
        else:
            # For INSERT/UPDATE/DELETE
            affected_rows = cursor.rowcount
            conn.commit()

            cursor.close()
            conn.close()

            return {
                "success": True,
                "affected_rows": affected_rows,
                "message": f"{affected_rows} row(s) affected",
            }

    except Exception as e:
        logger.error(f"Error in execute_raw_query: {e}")
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-password")
async def verify_password(request: PasswordVerifyRequest):
    """
    Verify a user's password against stored hash.

    Supports verification with different salt fields (email, phone, etc.)
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'

        # Determine salt field
        salt_field = request.salt_field or request.identifier_field

        # Fetch user record
        query = f'SELECT "password", "{salt_field}" FROM {full_table_name} WHERE "{request.identifier_field}" = %s'
        cursor.execute(query, (request.identifier_value,))
        user_record = cursor.fetchone()

        cursor.close()
        conn.close()

        if not user_record:
            return {"success": False, "verified": False, "message": "User not found"}

        stored_hash = user_record["password"]
        salt_value = user_record[salt_field]

        # Hash provided password with salt
        provided_hash = hash_password(request.password, str(salt_value))

        # Verify
        if provided_hash == stored_hash:
            return {
                "success": True,
                "verified": True,
                "message": "Password verified successfully",
            }
        else:
            return {"success": True, "verified": False, "message": "Invalid password"}

    except Exception as e:
        logger.error(f"Error in verify_password: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/{schema_name}/tables")
async def list_tables(schema_name: str):
    """
    List all tables in a schema.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
        """

        cursor.execute(query, (schema_name,))
        tables = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "schema": schema_name,
            "count": len(tables),
            "tables": [dict(row) for row in tables],
        }

    except Exception as e:
        logger.error(f"Error in list_tables: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/{schema_name}/table/{table_name}/columns")
async def get_table_columns(schema_name: str, table_name: str):
    """
    Get column information for a table.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """

        cursor.execute(query, (schema_name, table_name))
        columns = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "success": True,
            "schema": schema_name,
            "table": table_name,
            "count": len(columns),
            "columns": [dict(row) for row in columns],
        }

    except Exception as e:
        logger.error(f"Error in get_table_columns: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-operation")
async def bulk_operation(request: BulkOperationRequest):
    """
    Perform bulk operations (create, update, delete) on multiple records.

    For bulk updates and deletes, each record must contain filter fields.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        full_table_name = f'"{request.schema_name}"."{request.table_name}"'
        results = []

        if request.operation == "create":
            # Bulk create
            for record in request.records:
                if request.hash_password:
                    record = encrypt_password_in_data(record)
                record = serialize_json_fields(record)

                columns = list(record.keys())
                columns_str = ", ".join([f'"{c}"' for c in columns])
                placeholders = ", ".join(["%s"] * len(columns))
                values = [record[col] for col in columns]

                query = f"INSERT INTO {full_table_name} ({columns_str}) VALUES ({placeholders}) RETURNING *"
                cursor.execute(query, values)
                result = cursor.fetchone()
                results.append(dict(result))

        elif request.operation == "update":
            # Bulk update - each record needs filter and data
            for record in request.records:
                if "_filter" not in record or "_data" not in record:
                    raise HTTPException(
                        status_code=400,
                        detail="Bulk update requires '_filter' and '_data' keys in each record",
                    )

                filters = record["_filter"]
                data = record["_data"]

                if request.hash_password and "password" in data:
                    # Get salt for this specific record
                    where_clause, where_values = build_where_clause(filters)
                    salt_query = (
                        f'SELECT "email" FROM {full_table_name}'
                        + where_clause
                        + " LIMIT 1"
                    )
                    cursor.execute(salt_query, where_values)
                    salt_record = cursor.fetchone()
                    if salt_record:
                        data["password"] = hash_password(
                            data["password"], salt_record["email"]
                        )

                data = serialize_json_fields(data)

                set_parts = [f'"{key}" = %s' for key in data.keys()]
                set_clause = " SET " + ", ".join(set_parts)
                where_clause, where_values = build_where_clause(filters)

                query = (
                    f"UPDATE {full_table_name}"
                    + set_clause
                    + where_clause
                    + " RETURNING *"
                )
                values = list(data.values()) + where_values

                cursor.execute(query, values)
                updated = cursor.fetchall()
                results.extend([dict(row) for row in updated])

        elif request.operation == "delete":
            # Bulk delete - each record is a filter
            for filters in request.records:
                where_clause, where_values = build_where_clause(filters)
                query = f"DELETE FROM {full_table_name}" + where_clause + " RETURNING *"
                cursor.execute(query, where_values)
                deleted = cursor.fetchall()
                results.extend([dict(row) for row in deleted])

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "success": True,
            "operation": request.operation,
            "count": len(results),
            "data": results if len(results) <= 100 else None,
            "message": f"{len(results)} records processed"
            if len(results) > 100
            else None,
        }

    except Exception as e:
        logger.error(f"Error in bulk_operation: {e}")
        if conn:
            conn.rollback()
            conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Check database connection health"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()

        return {
            "success": True,
            "database": "connected",
            "message": "Database connection is healthy",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed")

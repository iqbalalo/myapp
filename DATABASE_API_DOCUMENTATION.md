# Database CRUD API Documentation

Complete guide for PostgreSQL database CRUD operations through REST API.

## Table of Contents
1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Endpoints](#endpoints)
4. [Request Examples](#request-examples)
5. [Password Handling](#password-handling)
6. [Advanced Features](#advanced-features)

---

## Overview

The Database CRUD API provides comprehensive REST endpoints for performing Create, Read, Update, and Delete operations on PostgreSQL databases. All endpoints require schema name specification for multi-tenant support.

**Base URL:** `http://localhost:8081/db`

**Key Features:**
- Full CRUD operations (Create, Read, Update, Delete)
- Multi-table JOIN queries
- Advanced filtering with operators
- Pagination and sorting
- Password hashing with configurable salt
- Bulk operations
- Raw SQL query execution
- Schema and table introspection

---

## Authentication

All endpoints require API key authentication via the `X-API-Key` header.

```bash
X-API-Key: your-api-key-here
```

---

## Endpoints

### 1. Read Records - `/db/read` (POST)

Read records from a table with filtering, pagination, and field selection.

**Request Body:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "filters": {
    "age": {"$gte": 18, "$lt": 65},
    "status": ["active", "pending"],
    "name": {"$ilike": "%john%"}
  },
  "limit": 100,
  "offset": 0,
  "include_fields": ["id", "name", "email"],
  "exclude_fields": null,
  "sort_by": "created_at",
  "sort_dir": "DESC"
}
```

**Filter Operators:**
- `$gt` - Greater than
- `$gte` - Greater than or equal
- `$lt` - Less than
- `$lte` - Less than or equal
- `$ne` - Not equal
- `$like` - SQL LIKE (case-sensitive)
- `$ilike` - SQL ILIKE (case-insensitive)
- Array values - IN operator

**Response:**
```json
{
  "success": true,
  "count": 25,
  "data": [
    {
      "id": 1,
      "name": "John Doe",
      "email": "john@example.com",
      "age": 30,
      "status": "active"
    }
  ]
}
```

---

### 2. Create Records - `/db/create` (POST)

Create one or multiple records in a table.

**Single Record:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "data": {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "phone": "+1234567890",
    "password": "mypassword123",
    "age": 28
  },
  "hash_password": true,
  "salt_field": "email"
}
```

**Multiple Records (Bulk):**
```json
{
  "schema_name": "public",
  "table_name": "products",
  "data": [
    {
      "name": "Product 1",
      "price": 29.99,
      "stock": 100
    },
    {
      "name": "Product 2",
      "price": 49.99,
      "stock": 50
    }
  ],
  "hash_password": false
}
```

**Response:**
```json
{
  "success": true,
  "count": 1,
  "data": {
    "id": 42,
    "name": "Jane Smith",
    "email": "jane@example.com",
    "created_at": "2025-11-08T10:30:00"
  }
}
```

---

### 3. Update Records - `/db/update` (POST)

Update records based on filter conditions.

**Request Body:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "filters": {
    "id": 42
  },
  "data": {
    "name": "Jane Doe",
    "age": 29,
    "updated_at": "2025-11-08T10:35:00"
  },
  "hash_password": false
}
```

**Update with Password:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "filters": {
    "email": "jane@example.com"
  },
  "data": {
    "password": "newpassword456"
  },
  "hash_password": true,
  "salt_field": "email"
}
```

**Response:**
```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "id": 42,
      "name": "Jane Doe",
      "email": "jane@example.com",
      "age": 29,
      "updated_at": "2025-11-08T10:35:00"
    }
  ]
}
```

---

### 4. Delete Records - `/db/delete` (POST)

Delete records based on filter conditions.

**Request Body:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "filters": {
    "id": 42
  }
}
```

**Delete Multiple Records:**
```json
{
  "schema_name": "public",
  "table_name": "logs",
  "filters": {
    "created_at": {"$lt": "2025-01-01"}
  }
}
```

**Response:**
```json
{
  "success": true,
  "count": 1,
  "message": "1 record(s) deleted"
}
```

---

### 5. Join Read - `/db/join-read` (POST)

Perform multi-table JOIN queries.

**Request Body:**
```json
{
  "schema_name": "public",
  "base_table": "orders",
  "joins": [
    {
      "table": "users",
      "type": "INNER",
      "on": "orders.user_id = users.id"
    },
    {
      "table": "products",
      "type": "LEFT",
      "on": "orders.product_id = products.id"
    }
  ],
  "filters": {
    "orders.status": "completed",
    "users.country": "USA"
  },
  "select_fields": [
    "orders.id",
    "orders.order_date",
    "users.name as user_name",
    "users.email",
    "products.name as product_name",
    "products.price"
  ],
  "limit": 50,
  "offset": 0,
  "sort_by": "orders.order_date",
  "sort_dir": "DESC"
}
```

**Join Types:** `INNER`, `LEFT`, `RIGHT`, `FULL`

**Response:**
```json
{
  "success": true,
  "count": 15,
  "data": [
    {
      "id": 1001,
      "order_date": "2025-11-05",
      "user_name": "John Doe",
      "email": "john@example.com",
      "product_name": "Widget A",
      "price": 29.99
    }
  ]
}
```

---

### 6. Raw Query - `/db/raw-query` (POST)

Execute custom SQL queries.

**SELECT Query:**
```json
{
  "schema_name": "public",
  "query": "SELECT u.name, COUNT(o.id) as order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id WHERE u.status = %s GROUP BY u.name HAVING COUNT(o.id) > %s",
  "params": ["active", 5],
  "read_only": true
}
```

**INSERT/UPDATE/DELETE Query:**
```json
{
  "schema_name": "public",
  "query": "UPDATE products SET stock = stock - %s WHERE id = %s",
  "params": [10, 123],
  "read_only": false
}
```

**Response (SELECT):**
```json
{
  "success": true,
  "count": 8,
  "data": [
    {
      "name": "John Doe",
      "order_count": 12
    }
  ]
}
```

**Response (INSERT/UPDATE/DELETE):**
```json
{
  "success": true,
  "affected_rows": 1,
  "message": "1 row(s) affected"
}
```

---

### 7. Verify Password - `/db/verify-password` (POST)

Verify user password against stored hash.

**Request Body:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "identifier_field": "email",
  "identifier_value": "john@example.com",
  "password": "mypassword123",
  "salt_field": "email"
}
```

**Response (Success):**
```json
{
  "success": true,
  "verified": true,
  "message": "Password verified successfully"
}
```

**Response (Failure):**
```json
{
  "success": true,
  "verified": false,
  "message": "Invalid password"
}
```

---

### 8. Bulk Operation - `/db/bulk-operation` (POST)

Perform bulk create, update, or delete operations.

**Bulk Create:**
```json
{
  "schema_name": "public",
  "table_name": "users",
  "operation": "create",
  "records": [
    {
      "name": "User 1",
      "email": "user1@example.com",
      "password": "pass123"
    },
    {
      "name": "User 2",
      "email": "user2@example.com",
      "password": "pass456"
    }
  ],
  "hash_password": true
}
```

**Bulk Update:**
```json
{
  "schema_name": "public",
  "table_name": "products",
  "operation": "update",
  "records": [
    {
      "_filter": {"id": 1},
      "_data": {"price": 99.99, "stock": 50}
    },
    {
      "_filter": {"id": 2},
      "_data": {"price": 79.99, "stock": 30}
    }
  ],
  "hash_password": false
}
```

**Bulk Delete:**
```json
{
  "schema_name": "public",
  "table_name": "logs",
  "operation": "delete",
  "records": [
    {"id": 100},
    {"id": 101},
    {"id": 102}
  ]
}
```

**Response:**
```json
{
  "success": true,
  "operation": "create",
  "count": 2,
  "data": [...]
}
```

---

### 9. List Tables - `/db/schema/{schema_name}/tables` (GET)

List all tables in a schema.

**Request:**
```bash
GET /db/schema/public/tables
```

**Response:**
```json
{
  "success": true,
  "schema": "public",
  "count": 5,
  "tables": [
    {
      "table_name": "users",
      "table_type": "BASE TABLE"
    },
    {
      "table_name": "orders",
      "table_type": "BASE TABLE"
    }
  ]
}
```

---

### 10. Get Table Columns - `/db/schema/{schema_name}/table/{table_name}/columns` (GET)

Get column information for a table.

**Request:**
```bash
GET /db/schema/public/table/users/columns
```

**Response:**
```json
{
  "success": true,
  "schema": "public",
  "table": "users",
  "count": 6,
  "columns": [
    {
      "column_name": "id",
      "data_type": "integer",
      "character_maximum_length": null,
      "is_nullable": "NO",
      "column_default": "nextval('users_id_seq'::regclass)"
    },
    {
      "column_name": "name",
      "data_type": "character varying",
      "character_maximum_length": 255,
      "is_nullable": "YES",
      "column_default": null
    }
  ]
}
```

---

### 11. Health Check - `/db/health` (GET)

Check database connection status.

**Request:**
```bash
GET /db/health
```

**Response:**
```json
{
  "success": true,
  "database": "connected",
  "message": "Database connection is healthy"
}
```

---

## Password Handling

The API provides automatic password hashing using SHA-256 with configurable salt fields.

### Creating User with Password

```json
{
  "schema_name": "public",
  "table_name": "users",
  "data": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1234567890",
    "password": "plaintext_password"
  },
  "hash_password": true,
  "salt_field": "email"
}
```

**How it works:**
1. Password is hashed as: `SHA256(password + salt_value)`
2. Salt field can be: `email`, `phone`, or any other unique field
3. Original password is replaced with hash before storage

### Verifying Password

```json
{
  "schema_name": "public",
  "table_name": "users",
  "identifier_field": "email",
  "identifier_value": "john@example.com",
  "password": "plaintext_password",
  "salt_field": "email"
}
```

**Process:**
1. Retrieves user by identifier
2. Gets salt value from specified field
3. Hashes provided password with salt
4. Compares with stored hash

---

## Advanced Features

### 1. Complex Filtering

Combine multiple operators:

```json
{
  "filters": {
    "age": {"$gte": 18, "$lte": 65},
    "name": {"$ilike": "%smith%"},
    "status": ["active", "pending"],
    "country": {"$ne": "USA"},
    "created_at": {"$gt": "2025-01-01"}
  }
}
```

### 2. Field Selection

**Include specific fields:**
```json
{
  "include_fields": ["id", "name", "email"]
}
```

**Exclude sensitive fields:**
```json
{
  "exclude_fields": ["password", "ssn", "credit_card"]
}
```

### 3. Pagination

```json
{
  "limit": 50,
  "offset": 100,
  "sort_by": "created_at",
  "sort_dir": "DESC"
}
```

### 4. JSON Field Support

Automatically serializes nested objects:

```json
{
  "data": {
    "name": "Product",
    "metadata": {
      "category": "electronics",
      "tags": ["new", "sale"]
    },
    "features": ["wifi", "bluetooth", "waterproof"]
  }
}
```

### 5. Multi-Table Operations

Complex JOIN with multiple tables:

```json
{
  "base_table": "orders",
  "joins": [
    {
      "table": "users",
      "type": "INNER",
      "on": "orders.user_id = users.id"
    },
    {
      "table": "products",
      "type": "LEFT",
      "on": "orders.product_id = products.id"
    },
    {
      "table": "shipping",
      "type": "LEFT",
      "on": "orders.id = shipping.order_id"
    }
  ]
}
```

---

## Complete Usage Examples

### Example 1: User Management System

**1. Create Users with Passwords:**
```bash
curl -X POST http://localhost:8081/db/create \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "table_name": "users",
    "data": [
      {
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "phone": "+1234567890",
        "password": "alice_password",
        "role": "admin"
      },
      {
        "name": "Bob Smith",
        "email": "bob@example.com",
        "phone": "+1987654321",
        "password": "bob_password",
        "role": "user"
      }
    ],
    "hash_password": true,
    "salt_field": "email"
  }'
```

**2. Login (Verify Password):**
```bash
curl -X POST http://localhost:8081/db/verify-password \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "table_name": "users",
    "identifier_field": "email",
    "identifier_value": "alice@example.com",
    "password": "alice_password"
  }'
```

**3. Get User Profile:**
```bash
curl -X POST http://localhost:8081/db/read \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "table_name": "users",
    "filters": {
      "email": "alice@example.com"
    },
    "exclude_fields": ["password"]
  }'
```

**4. Update User:**
```bash
curl -X POST http://localhost:8081/db/update \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "table_name": "users",
    "filters": {
      "email": "alice@example.com"
    },
    "data": {
      "phone": "+1555555555",
      "last_login": "2025-11-08T15:30:00"
    }
  }'
```

---

### Example 2: E-commerce Orders

**1. Get Orders with User and Product Info:**
```bash
curl -X POST http://localhost:8081/db/join-read \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "base_table": "orders",
    "joins": [
      {
        "table": "users",
        "type": "INNER",
        "on": "orders.user_id = users.id"
      },
      {
        "table": "products",
        "type": "INNER",
        "on": "orders.product_id = products.id"
      }
    ],
    "filters": {
      "orders.status": "pending",
      "orders.created_at": {"$gte": "2025-11-01"}
    },
    "select_fields": [
      "orders.id",
      "orders.order_date",
      "orders.total",
      "users.name as customer_name",
      "users.email",
      "products.name as product_name",
      "products.price"
    ],
    "sort_by": "orders.created_at",
    "sort_dir": "DESC",
    "limit": 100
  }'
```

**2. Update Order Status:**
```bash
curl -X POST http://localhost:8081/db/update \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "table_name": "orders",
    "filters": {
      "id": 1001
    },
    "data": {
      "status": "shipped",
      "shipped_at": "2025-11-08T16:00:00"
    }
  }'
```

---

### Example 3: Analytics Query

**Get Sales Report:**
```bash
curl -X POST http://localhost:8081/db/raw-query \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_name": "public",
    "query": "SELECT DATE(order_date) as date, COUNT(*) as order_count, SUM(total) as revenue FROM orders WHERE status = %s AND order_date >= %s GROUP BY DATE(order_date) ORDER BY date DESC",
    "params": ["completed", "2025-11-01"],
    "read_only": true
  }'
```

---

## Error Handling

All endpoints return structured error responses:

```json
{
  "detail": "Error message describing what went wrong"
}
```

**Common HTTP Status Codes:**
- `200` - Success
- `400` - Bad Request (invalid input)
- `401` - Unauthorized (invalid API key)
- `500` - Internal Server Error (database or server issue)
- `503` - Service Unavailable (database connection failed)

---

## Best Practices

1. **Always specify schema_name** for proper multi-tenant isolation
2. **Use filters for DELETE operations** to prevent accidental bulk deletions
3. **Exclude password fields** when reading user data
4. **Use pagination** for large result sets
5. **Leverage bulk operations** for multiple record operations
6. **Use prepared statements** (params) in raw queries to prevent SQL injection
7. **Set read_only=true** for SELECT queries in raw-query endpoint
8. **Use appropriate JOIN types** based on data requirements
9. **Index frequently filtered columns** for better performance
10. **Hash passwords** using the built-in password hashing feature

---

## Security Considerations

1. **API Key Protection:** Never expose API keys in client-side code
2. **SQL Injection:** Use parameterized queries (filters, params) instead of string concatenation
3. **Password Security:** Always use `hash_password: true` for user credentials
4. **Field Exclusion:** Exclude sensitive fields (password, SSN, etc.) in responses
5. **Rate Limiting:** Implement rate limiting on production deployments
6. **HTTPS:** Always use HTTPS in production
7. **Input Validation:** API validates all inputs, but additional validation is recommended
8. **Least Privilege:** Grant minimal database permissions to API database user

---

## Support & Troubleshooting

### Connection Issues
Check database configuration in docker-compose.yml or .env file:
```
DB_HOST=db
DB_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
```

### Health Check
Use the health endpoint to verify database connectivity:
```bash
curl -X GET http://localhost:8081/db/health \
  -H "X-API-Key: your-api-key"
```

### Schema/Table Discovery
List available tables and columns:
```bash
# List tables
curl -X GET http://localhost:8081/db/schema/public/tables \
  -H "X-API-Key: your-api-key"

# Get table structure
curl -X GET http://localhost:8081/db/schema/public/table/users/columns \
  -H "X-API-Key: your-api-key"
```

---

## Changelog

**Version 2.0.0** (Current)
- Complete CRUD API implementation
- Multi-table JOIN support
- Advanced filtering with operators
- Password hashing and verification
- Bulk operations
- Raw query execution
- Schema introspection
- Comprehensive documentation

---

For more information, visit the interactive API documentation at: `http://localhost:8081/docs`

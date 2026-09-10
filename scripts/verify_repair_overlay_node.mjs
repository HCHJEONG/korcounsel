// Analysis-only cross-runtime validation of the full typed date overlay.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
const [directory, packageRoot, reportPath] = process.argv.slice(2);
const require = createRequire(join(resolve(packageRoot), 'package.json'));
const { DuckDBInstance } = require('@duckdb/node-api');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
const expected = JSON.parse(readFileSync(join(directory, 'node-expected.json'), 'utf8'));
const parquetPath = resolve(directory, 'repair-overlay.parquet');
const parquetHash = hash(readFileSync(parquetPath));
if (parquetHash !== manifest.files['repair-overlay.parquet'].sha256) throw new Error('PARQUET_HASH_MISMATCH');
const instance = await DuckDBInstance.create(':memory:');
const connection = await instance.connect();
try {
  const reader = await connection.runAndReadAll(
    'SELECT * FROM read_parquet(?) ORDER BY position', [parquetPath]);
  const rows = reader.getRowsJson();
  const actualHash = hash(JSON.stringify(rows));
  if (actualHash !== expected.sha256 || rows.length !== expected.rows) throw new Error('OVERLAY_VALUE_MISMATCH');
  const result = {rows: rows.length, parquet_sha256: parquetHash, value_sha256: actualHash,
    all_cells_equal: true, node: process.version, duckdb_node_api: require('@duckdb/node-api/package.json').version,
    rules_version: manifest.rules_version, scope: 'FULL_REPAIR_OVERLAY_NOT_60_COLUMN_CORPUS'};
  writeFileSync(reportPath, JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
} finally {
  connection.closeSync();
  instance.closeSync();
}

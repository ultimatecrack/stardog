# From SQL joins to SPARQL

If you can write a SQL query with an inner join, you already understand most of SPARQL. In SQL you join tables on keys; in SPARQL you join triple patterns on shared variables, and no JOIN keyword is needed.

This lesson assumes you know SELECT, WHERE and joins in SQL. We introduce RDF triples, IRIs and prefixes, then translate a series of SQL queries into SPARQL: a filter becomes FILTER, a LEFT JOIN becomes OPTIONAL, and GROUP BY works almost the same.

Finally we look at property paths, which answer questions like "all prerequisites at any depth" that would need a recursive query in SQL. This is the foundation for working with knowledge graphs.

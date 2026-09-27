# Getting started with pandas DataFrames

A DataFrame is a table of labelled columns, and pandas is the standard Python library for working with them. Before starting this lesson you should be comfortable with Python lists and dictionaries, and with NumPy arrays, because every DataFrame column is stored as a NumPy array under the hood.

We load a CSV file with `pd.read_csv`, look at the first rows with `head()`, and select columns by name. Filtering rows uses boolean masks, exactly like NumPy. Grouping with `groupby` and aggregating with `mean` or `count` answers most everyday questions, such as the average score per course.

Missing values appear as NaN. Use `isna()` to find them and `fillna()` or `dropna()` to deal with them. At the end of the lesson you will merge two DataFrames on a shared key, which works much like a SQL join.

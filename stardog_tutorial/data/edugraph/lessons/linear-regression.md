# Understanding linear regression

Linear regression predicts a number, such as a house price, from one or more input features by fitting a straight line (or a plane) through the data. To follow this lesson you need basic statistics, in particular mean, variance and correlation, and some linear algebra: vectors, matrices and the matrix product.

We fit the line by minimising the mean squared error. For small problems there is a closed-form solution using matrix inversion; for large ones we use gradient descent, which repeatedly nudges the coefficients downhill on the error surface. We prepare the data with pandas and check the fit with the R-squared value and a plot of the residuals.

Regularisation, such as ridge regression, keeps coefficients small and helps when features are correlated.

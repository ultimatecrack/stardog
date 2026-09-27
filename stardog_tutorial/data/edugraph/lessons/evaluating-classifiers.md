# Evaluating classifiers

A classifier that is right 95% of the time can still be useless, for example when only 2% of emails are spam. This lesson shows how to measure classification models properly.

You should already know how logistic regression and decision trees make predictions. We build a confusion matrix and derive precision, recall and the F1 score, then draw ROC curves and compute the area under the curve.

To avoid fooling ourselves we never evaluate on the training data: we use a held-out test set and k-fold cross-validation. The lesson ends with overfitting, and how learning curves reveal it.

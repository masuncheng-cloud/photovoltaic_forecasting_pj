from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

MODEL_VERBOSE = os.getenv("PV_MODEL_VERBOSE", "0") == "1"


@dataclass
class TabularModelBundle:
    model: object
    feature_cols: list[str]
    cat_cols: list[str]
    num_cols: list[str]
    target_col: str
    model_type: str = "catboost"   # "catboost", "lightgbm", or "ensemble"
    sub_models: list = field(default_factory=list)  # for ensemble: list of (weight, bundle)


@dataclass
class TabularClassifierBundle:
    model: object
    feature_cols: list[str]
    cat_cols: list[str]
    num_cols: list[str]
    target_col: str


def _prepare_features(df: pd.DataFrame, feature_cols: Sequence[str], cat_cols: Sequence[str] | None = None) -> pd.DataFrame:
    cat_cols = list(cat_cols or [])
    out = df.copy()
    for c in feature_cols:
        if c not in out.columns:
            out[c] = 'unknown' if c in cat_cols else np.nan
    for c in cat_cols:
        out[c] = out[c].astype('string').fillna('unknown')
    return out[list(feature_cols)].copy()


def _finite_target_mask(series: pd.Series) -> np.ndarray:
    vals = pd.to_numeric(series, errors='coerce').to_numpy(dtype=float)
    return np.isfinite(vals)


def _build_catboost_regressor(X_train, y_train, X_valid, y_valid,
                               cat_features: list[int], w_train,
                               task_params: dict | None = None) -> "CatBoostRegressor":
    from catboost import CatBoostRegressor
    defaults = dict(
        iterations=2000,
        depth=8,
        learning_rate=0.02,
        l2_leaf_reg=2.0,
        bagging_temperature=0.7,
        random_strength=0.3,
        loss_function='RMSE',
        eval_metric='RMSE',
        verbose=100 if MODEL_VERBOSE else False,
        random_seed=42,
        early_stopping_rounds=150,
    )
    if task_params:
        defaults.update(task_params)
    model = CatBoostRegressor(**defaults)
    model.fit(X_train, y_train, eval_set=(X_valid, y_valid),
              cat_features=cat_features, sample_weight=w_train, use_best_model=True)
    return model


def _build_lightgbm_regressor(X_train, y_train, X_valid, y_valid,
                                w_train,
                                cat_features: list[str],
                                task_params: dict | None = None) -> "LGBMRegressor":
    from lightgbm import LGBMRegressor
    defaults = dict(
        n_estimators=2500,
        max_depth=10,
        num_leaves=127,
        learning_rate=0.02,
        reg_lambda=1.5,
        reg_alpha=0.3,
        min_child_samples=15,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    if task_params:
        defaults.update(task_params)
    model = LGBMRegressor(**defaults)
    model.fit(
        X_train, y_train,
        eval_set=[(X_valid, y_valid)],
        callbacks=[
            _make_lgbm_early_stopping(150),
            _make_lgbm_log_evaluation(100 if MODEL_VERBOSE else 0),
        ] if w_train is None else [
            _make_lgbm_early_stopping(150),
        ],
        sample_weight=w_train,
    )
    return model


def _build_catboost_classifier(X_train, y_train, X_valid, y_valid,
                                 cat_features: list[int], w_train,
                                 task_params: dict | None = None) -> "CatBoostClassifier":
    from catboost import CatBoostClassifier
    defaults = dict(
        iterations=1500,
        depth=8,
        learning_rate=0.02,
        l2_leaf_reg=2.0,
        bagging_temperature=0.7,
        random_strength=0.3,
        loss_function='Logloss',
        eval_metric='AUC',
        verbose=100 if MODEL_VERBOSE else False,
        random_seed=42,
        early_stopping_rounds=150,
    )
    if task_params:
        defaults.update(task_params)
    model = CatBoostClassifier(**defaults)
    model.fit(X_train, y_train, eval_set=(X_valid, y_valid),
              cat_features=cat_features, sample_weight=w_train, use_best_model=True)
    return model


def _make_lgbm_early_stopping(rounds: int):
    from lightgbm import early_stopping, log_evaluation
    return early_stopping(stopping_rounds=rounds, verbose=False)


def _make_lgbm_log_evaluation(period: int):
    from lightgbm import log_evaluation
    return log_evaluation(period=period)


def _get_lgbm_cat_indices(feature_cols: list[str], cat_cols: list[str]) -> list[str]:
    """Return cat column names for LightGBM categorical handling."""
    return [c for c in cat_cols if c in feature_cols]


def fit_tabular_regressor(train_df: pd.DataFrame,
                          valid_df: pd.DataFrame,
                          feature_cols: Sequence[str],
                          target_col: str,
                          cat_cols: Sequence[str] | None = None,
                          sample_weight_col: str | None = None,
                          task_params: dict | None = None,
                          use_ensemble: bool = True):
    cat_cols = list(cat_cols or [])
    num_cols = [c for c in feature_cols if c not in cat_cols]
    train_df = train_df.copy()
    valid_df = valid_df.copy()
    m_train = _finite_target_mask(train_df[target_col])
    m_valid = _finite_target_mask(valid_df[target_col])
    train_df = train_df.loc[m_train].copy()
    valid_df = valid_df.loc[m_valid].copy()
    X_train = _prepare_features(train_df, feature_cols, cat_cols)
    X_valid = _prepare_features(valid_df, feature_cols, cat_cols)
    y_train = pd.to_numeric(train_df[target_col], errors='coerce').to_numpy(dtype=float)
    y_valid = pd.to_numeric(valid_df[target_col], errors='coerce').to_numpy(dtype=float)
    w_train = None if sample_weight_col is None else pd.to_numeric(train_df[sample_weight_col], errors='coerce').fillna(1.0).to_numpy(dtype=float)

    # Try CatBoost first, then LightGBM, then ensemble
    sub_models = []
    primary_bundle = None

    # ---- CatBoost ----
    try:
        from catboost import CatBoostRegressor
        cat_idx = [list(feature_cols).index(c) for c in cat_cols if c in feature_cols]
        cb_model = _build_catboost_regressor(X_train, y_train, X_valid, y_valid, cat_idx, w_train, task_params)
        cb_pred = cb_model.predict(X_valid)
        cb_rmse = float(np.sqrt(np.mean((y_valid - cb_pred) ** 2)))
        sub_models.append({'type': 'catboost', 'model': cb_model, 'rmse': cb_rmse})
    except Exception:
        cb_rmse = np.inf

    # ---- LightGBM ----
    lgbm_rmse = np.inf
    try:
        lgbm_cat = _get_lgbm_cat_indices(list(feature_cols), cat_cols)
        if lgbm_cat:
            for c in lgbm_cat:
                X_train[c] = X_train[c].astype('category')
                X_valid[c] = X_valid[c].astype('category')
        lgbm_model = _build_lightgbm_regressor(X_train, y_train, X_valid, y_valid, w_train, lgbm_cat, task_params)
        lgbm_pred = lgbm_model.predict(X_valid)
        lgbm_rmse = float(np.sqrt(np.mean((y_valid - lgbm_pred) ** 2)))
        sub_models.append({'type': 'lightgbm', 'model': lgbm_model, 'rmse': lgbm_rmse})
    except Exception:
        pass

    # ---- Ensemble ----
    if use_ensemble and len(sub_models) >= 2:
        # Weight by inverse RMSE (better model gets higher weight)
        rmses = np.array([s['rmse'] for s in sub_models])
        weights = 1.0 / (rmses + 1e-9)
        weights = weights / weights.sum()
        for i, s in enumerate(sub_models):
            s['weight'] = float(weights[i])
        ensemble_pred = sum(s['weight'] * s['model'].predict(
            X_valid if s['type'] != 'catboost' else X_valid
        ) for s in sub_models)
        ensemble_rmse = float(np.sqrt(np.mean((y_valid - ensemble_pred) ** 2)))
        # Use ensemble if it beats the best single model
        best_single_rmse = min(cb_rmse, lgbm_rmse)
        if ensemble_rmse < best_single_rmse * 0.99:
            sub_models.append({'type': 'ensemble', 'rmse': ensemble_rmse})
            primary_bundle = TabularModelBundle(
                model=None,
                feature_cols=list(feature_cols),
                cat_cols=cat_cols,
                num_cols=num_cols,
                target_col=target_col,
                model_type='ensemble',
                sub_models=[(s.get('weight', 1.0), s['model'], s['type']) for s in sub_models if s['type'] != 'ensemble'],
            )
        else:
            best = min(sub_models[:-1], key=lambda s: s['rmse'])
            primary_bundle = TabularModelBundle(
                model=best['model'],
                feature_cols=list(feature_cols),
                cat_cols=cat_cols,
                num_cols=num_cols,
                target_col=target_col,
                model_type=best['type'],
                sub_models=[],
            )
    elif sub_models:
        best = min(sub_models, key=lambda s: s['rmse'])
        primary_bundle = TabularModelBundle(
            model=best['model'],
            feature_cols=list(feature_cols),
            cat_cols=cat_cols,
            num_cols=num_cols,
            target_col=target_col,
            model_type=best['type'],
            sub_models=[],
        )
    else:
        # Fallback: sklearn pipeline — must separate numeric and categorical columns
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OrdinalEncoder

        # Only true numeric columns go to SimpleImputer (exclude ALL categorical)
        _num_cols = [c for c in feature_cols if c not in cat_cols]
        # Encode categorical columns with OrdinalEncoder so RandomForest can consume them
        _cat_ord = [c for c in cat_cols if c in feature_cols]
        transformers = []
        if _num_cols:
            transformers.append(('num', Pipeline([('imputer', SimpleImputer(strategy='median'))]), _num_cols))
        if _cat_ord:
            transformers.append(('cat', Pipeline([('encoder', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1))]), _cat_ord))

        pre = ColumnTransformer(transformers, remainder='drop')
        model = Pipeline([
            ('pre', pre),
            ('rf', RandomForestRegressor(n_estimators=250, random_state=42, n_jobs=-1, min_samples_leaf=3)),
        ])
        model.fit(X_train, y_train)
        return TabularModelBundle(model=model, feature_cols=list(feature_cols), cat_cols=cat_cols, num_cols=num_cols, target_col=target_col, model_type='sklearn', sub_models=[])

    return primary_bundle


def fit_tabular_classifier(train_df: pd.DataFrame,
                          valid_df: pd.DataFrame,
                          feature_cols: Sequence[str],
                          target_col: str,
                          cat_cols: Sequence[str] | None = None,
                          sample_weight_col: str | None = None,
                          task_params: dict | None = None):
    cat_cols = list(cat_cols or [])
    num_cols = [c for c in feature_cols if c not in cat_cols]
    train_df = train_df.copy()
    valid_df = valid_df.copy()
    m_train = _finite_target_mask(train_df[target_col])
    m_valid = _finite_target_mask(valid_df[target_col])
    train_df = train_df.loc[m_train].copy()
    valid_df = valid_df.loc[m_valid].copy()
    X_train = _prepare_features(train_df, feature_cols, cat_cols)
    X_valid = _prepare_features(valid_df, feature_cols, cat_cols)
    y_train = pd.to_numeric(train_df[target_col], errors='coerce').fillna(0).astype(int).to_numpy()
    y_valid = pd.to_numeric(valid_df[target_col], errors='coerce').fillna(0).astype(int).to_numpy()
    w_train = None if sample_weight_col is None else pd.to_numeric(train_df[sample_weight_col], errors='coerce').fillna(1.0).to_numpy(dtype=float)

    try:
        from catboost import CatBoostClassifier
        cat_idx = [list(feature_cols).index(c) for c in cat_cols if c in feature_cols]
        model = _build_catboost_classifier(X_train, y_train, X_valid, y_valid, cat_idx, w_train, task_params)
        return TabularClassifierBundle(model=model, feature_cols=list(feature_cols), cat_cols=cat_cols, num_cols=num_cols, target_col=target_col)
    except Exception:
        from sklearn.compose import ColumnTransformer
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

        # For the fallback, encode categorical columns with OrdinalEncoder
        # so they don't get sent to SimpleImputer which only handles numeric data
        cat_for_ordinal = [c for c in cat_cols if c in feature_cols]
        cat_for_onehot = [c for c in cat_cols if c in feature_cols and c not in cat_for_ordinal]
        transformers = []
        if num_cols:
            transformers.append(('num', Pipeline([('imputer', SimpleImputer(strategy='median'))]), num_cols))
        if cat_for_ordinal:
            transformers.append(('ord', OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1), cat_for_ordinal))
        if cat_for_onehot:
            transformers.append(('cat', Pipeline([('imputer', SimpleImputer(strategy='most_frequent')), ('onehot', OneHotEncoder(handle_unknown='ignore'))]), cat_for_onehot))

        pre = ColumnTransformer(transformers, remainder='drop')
        model = Pipeline([
            ('pre', pre),
            ('rf', RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1, min_samples_leaf=3, class_weight='balanced_subsample')),
        ])
        model.fit(X_train, y_train)
        return TabularClassifierBundle(model=model, feature_cols=list(feature_cols), cat_cols=cat_cols, num_cols=num_cols, target_col=target_col)


def predict_bundle(bundle: TabularModelBundle, df: pd.DataFrame) -> np.ndarray:
    x = _prepare_features(df, bundle.feature_cols, bundle.cat_cols)
    if bundle.model_type == 'ensemble' and bundle.sub_models:
        preds = []
        for w, model, mtype in bundle.sub_models:
            x_use = x.copy()
            if mtype == 'lightgbm':
                for c in bundle.cat_cols:
                    if c in x_use.columns:
                        x_use[c] = x_use[c].astype('category')
            preds.append(w * model.predict(x_use))
        return sum(preds)
    elif bundle.model_type == 'lightgbm':
        x_out = x.copy()
        for c in bundle.cat_cols:
            if c in x_out.columns:
                x_out[c] = x_out[c].astype('category')
        return bundle.model.predict(x_out)
    else:
        return bundle.model.predict(x)


def predict_proba_bundle(bundle: TabularClassifierBundle, df: pd.DataFrame) -> np.ndarray:
    x = _prepare_features(df, bundle.feature_cols, bundle.cat_cols)
    if hasattr(bundle.model, 'predict_proba'):
        proba = bundle.model.predict_proba(x)
        if isinstance(proba, list):
            proba = np.asarray(proba)
        if proba.ndim == 2 and proba.shape[1] >= 2:
            return proba[:, 1]
    pred = bundle.model.predict(x)
    return np.asarray(pred, dtype=float)

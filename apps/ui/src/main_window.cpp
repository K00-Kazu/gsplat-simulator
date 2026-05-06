#include "main_window.h"

#include "preview_viewport_widget.h"
#include "render_worker.h"

#include <algorithm>
#include <cmath>
#include <QAction>
#include <QDockWidget>
#include <QFrame>
#include <QFileDialog>
#include <QFontMetrics>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QMenuBar>
#include <QPushButton>
#include <QResizeEvent>
#include <QSizePolicy>
#include <QStatusBar>
#include <QVBoxLayout>
#include <QWidget>

namespace
{
constexpr auto kDefaultPreviewScenePath = "assets/sample_point_cloud.ply";
constexpr double kCameraPanStep = 0.2;
constexpr double kCameraOrbitStepDegrees = 12.0;
constexpr double kCameraMaxPitchDegrees = 80.0;
constexpr double kCameraDefaultFocalLengthPx = 900.0;
constexpr double kCameraMinFocalLengthPx = 100.0;
constexpr double kCameraMaxFocalLengthPx = 3000.0;
constexpr double kCameraZoomFactor = 1.15;
constexpr double kRobotTranslationStepMeters = 0.2;
constexpr double kRobotRotationStepDegrees = 15.0;

QFrame* buildControlCard(QWidget* parent, const QString& objectName)
{
    auto* card = new QFrame(parent);
    card->setObjectName(objectName);
    card->setFrameShape(QFrame::NoFrame);
    return card;
}

QPushButton* buildRingButton(
    QWidget* parent,
    const QString& objectName,
    const QString& label,
    const QString& accessibleName,
    const QString& tooltip)
{
    auto* button = new QPushButton(label, parent);
    button->setObjectName(objectName);
    button->setAccessibleName(accessibleName);
    button->setToolTip(tooltip);
    button->setProperty("directional", true);
    button->setProperty("controlRingButton", true);
    button->setFixedSize(42, 42);
    return button;
}
}

MainWindow::MainWindow(QWidget* parent, bool autoSubscribe)
    : QMainWindow(parent)
{
    scene_ply_path_ = QString::fromUtf8(kDefaultPreviewScenePath);
    camera_focal_length_px_ = kCameraDefaultFocalLengthPx;

    setWindowTitle("gsplat-simulator UI");
    resize(1280, 720);

    auto* file_menu = menuBar()->addMenu(QStringLiteral("File"));
    file_menu->setObjectName("fileMenu");
    auto* open_scene_action = file_menu->addAction(QStringLiteral("Open Scene..."));
    open_scene_action->setObjectName("openSceneAction");
    connect(open_scene_action, &QAction::triggered, this, &MainWindow::browsePreviewScenePath);

    auto* central_widget = new QWidget(this);
    auto* layout = new QVBoxLayout(central_widget);
    layout->setContentsMargins(32, 32, 32, 32);
    layout->setSpacing(12);

    auto* title_label = new QLabel("gsplat-simulator UI", central_widget);
    title_label->setStyleSheet("font-size: 28px; font-weight: 700;");

    auto* subtitle_label = new QLabel(
        "Preview camera frame subscriber for render output",
        central_widget);
    subtitle_label->setWordWrap(true);
    subtitle_label->setStyleSheet("color: #5f6368; font-size: 14px;");

    preview_viewport_ = new PreviewViewportWidget(central_widget);

    layout->addWidget(title_label);
    layout->addWidget(subtitle_label);
    layout->addSpacing(12);
    layout->addWidget(preview_viewport_, 1);

    setCentralWidget(central_widget);

    auto* camera_controls_dock = new QDockWidget("Controls", this);
    camera_controls_dock->setObjectName("cameraControlsDock");
    camera_controls_dock->setAllowedAreas(Qt::LeftDockWidgetArea | Qt::RightDockWidgetArea);
    camera_controls_dock->setFeatures(QDockWidget::NoDockWidgetFeatures);

    auto* camera_controls_panel = new QWidget(camera_controls_dock);
    camera_controls_panel->setObjectName("cameraControlsPanel");
    camera_controls_panel->setMinimumWidth(560);
    camera_controls_panel->setStyleSheet(
        "#cameraControlsPanel {"
        "  background: #f6f1e8;"
        "}"
        "#cameraControlsPanel QFrame[card='true'] {"
        "  background: #fffdfa;"
        "  border: 1px solid #d7cbbb;"
        "  border-radius: 8px;"
        "}"
        "#cameraControlsPanel QLabel[sectionTitle='true'] {"
        "  color: #202124;"
        "  font-size: 15px;"
        "  font-weight: 700;"
        "}"
        "#cameraControlsPanel QLabel[groupTitle='true'] {"
        "  color: #202124;"
        "  font-size: 13px;"
        "  font-weight: 700;"
        "  letter-spacing: 0px;"
        "}"
        "#cameraControlsPanel QLabel[valueChip='true'] {"
        "  color: #3c4043;"
        "  font-size: 12px;"
        "  line-height: 1.35;"
        "  background: #f4efe7;"
        "  border: 1px solid #dfd3c3;"
        "  border-radius: 8px;"
        "  padding: 6px 8px;"
        "}"
        "#cameraControlsPanel QPushButton {"
        "  min-height: 32px;"
        "  padding: 6px 10px;"
        "  border-radius: 8px;"
        "  border: 1px solid #c9bba9;"
        "  background: #fbf7f1;"
        "  color: #24302b;"
        "  font-size: 13px;"
        "  font-weight: 600;"
        "}"
        "#cameraControlsPanel QPushButton:hover {"
        "  background: #f0e4d3;"
        "  border-color: #b8a58d;"
        "}"
        "#cameraControlsPanel QPushButton:pressed {"
        "  background: #e5d5c2;"
        "}"
        "#cameraControlsPanel QPushButton[primaryAction='true'] {"
        "  background: #dce8de;"
        "  border: 1px solid #8aa38f;"
        "  color: #1f352a;"
        "}"
        "#cameraControlsPanel QPushButton[primaryAction='true']:hover {"
        "  background: #d0dfd3;"
        "  border-color: #728f79;"
        "}"
        "#cameraControlsPanel QPushButton[secondaryAction='true'] {"
        "  background: #f4efe7;"
        "  border-style: dashed;"
        "}"
        "#cameraControlsPanel QPushButton[directional='true'] {"
        "  min-width: 56px;"
        "  min-height: 36px;"
        "  border-radius: 8px;"
        "}"
        "#cameraControlsPanel QPushButton[controlRingButton='true'] {"
        "  min-width: 42px;"
        "  max-width: 42px;"
        "  min-height: 42px;"
        "  max-height: 42px;"
        "  padding: 0px;"
        "  border-radius: 21px;"
        "  background: #fffdfa;"
        "  font-size: 12px;"
        "  font-weight: 700;"
        "}"
        "#cameraControlsPanel QPushButton[controlRingButton='true']:hover {"
        "  background: #eef5ef;"
        "  border-color: #8aa38f;"
        "}"
        "#cameraControlsPanel QPushButton[axisAction='true'] {"
        "  min-width: 80px;"
        "}"
        "#cameraControlsPanel QPushButton[placeholderAction='true'] {"
        "  color: #53635a;"
        "}");

    auto* panel_layout = new QVBoxLayout(camera_controls_panel);
    panel_layout->setContentsMargins(12, 12, 12, 12);
    panel_layout->setSpacing(0);

    auto* controls_body = new QWidget(camera_controls_panel);
    controls_body->setObjectName("controlsBody");
    auto* controls_body_layout = new QHBoxLayout(controls_body);
    controls_body_layout->setContentsMargins(0, 0, 0, 0);
    controls_body_layout->setSpacing(12);

    auto* preview_controls_group = buildControlCard(controls_body, "previewControlsGroup");
    auto* preview_controls_layout = new QVBoxLayout(preview_controls_group);
    preview_controls_layout->setContentsMargins(0, 0, 0, 0);
    preview_controls_layout->setSpacing(10);
    auto* preview_controls_title = new QLabel("Preview camera controls", preview_controls_group);
    preview_controls_title->setProperty("groupTitle", true);
    preview_controls_layout->addWidget(preview_controls_title);

    auto* scene_card = buildControlCard(preview_controls_group, "sceneControlCard");
    scene_card->setProperty("card", true);
    scene_card->setMaximumHeight(78);
    auto* scene_layout = new QGridLayout(scene_card);
    scene_layout->setContentsMargins(10, 10, 10, 10);
    scene_layout->setHorizontalSpacing(8);
    scene_layout->setVerticalSpacing(0);

    auto* scene_section_label = new QLabel("Scene", scene_card);
    scene_section_label->setProperty("sectionTitle", true);

    auto* scene_view_button = new QPushButton("Scene View", scene_card);
    scene_view_button->setObjectName("sceneViewButton");
    scene_view_button->setProperty("secondaryAction", true);
    scene_view_button->setProperty("placeholderAction", true);
    scene_view_button->setMaximumWidth(92);
    scene_view_button->setToolTip("UI-only placeholder for a future scene view action.");

    auto* fit_button = new QPushButton("Fit", scene_card);
    fit_button->setObjectName("fitSceneButton");
    fit_button->setProperty("secondaryAction", true);
    fit_button->setMaximumWidth(52);
    fit_button->setToolTip("Reset preview zoom, pan, and rotation.");

    current_scene_label_ = new QLabel(scene_card);
    current_scene_label_->setObjectName("currentSceneLabel");
    current_scene_label_->setProperty("valueChip", true);
    current_scene_label_->setWordWrap(false);
    current_scene_label_->setMinimumWidth(80);
    current_scene_label_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);

    scene_layout->addWidget(scene_section_label, 0, 0);
    scene_layout->addWidget(current_scene_label_, 0, 1);
    scene_layout->addWidget(scene_view_button, 0, 2);
    scene_layout->addWidget(fit_button, 0, 3);
    scene_layout->setColumnStretch(1, 1);

    connect(fit_button, &QPushButton::clicked, this, &MainWindow::resetPreviewCameraView);

    auto* zoom_card = buildControlCard(preview_controls_group, "zoomControlCard");
    zoom_card->setProperty("card", true);
    auto* zoom_layout = new QVBoxLayout(zoom_card);
    zoom_layout->setContentsMargins(14, 14, 14, 14);
    zoom_layout->setSpacing(10);

    auto* zoom_section_label = new QLabel("Zoom", zoom_card);
    zoom_section_label->setProperty("sectionTitle", true);

    camera_zoom_label_ = new QLabel(zoom_card);
    camera_zoom_label_->setObjectName("cameraZoomLabel");
    camera_zoom_label_->setProperty("valueChip", true);
    camera_zoom_label_->setWordWrap(true);

    auto* zoom_controls_layout = new QGridLayout();
    zoom_controls_layout->setHorizontalSpacing(8);
    zoom_controls_layout->setVerticalSpacing(8);

    auto* zoom_in_button = new QPushButton("Zoom In", zoom_card);
    zoom_in_button->setObjectName("zoomInButton");
    zoom_in_button->setProperty("primaryAction", true);
    auto* zoom_out_button = new QPushButton("Zoom Out", zoom_card);
    zoom_out_button->setObjectName("zoomOutButton");
    zoom_out_button->setProperty("primaryAction", true);
    zoom_controls_layout->addWidget(zoom_in_button, 0, 0);
    zoom_controls_layout->addWidget(zoom_out_button, 0, 1);

    connect(zoom_in_button, &QPushButton::clicked, this, [this]() { adjustCameraZoom(kCameraZoomFactor); });
    connect(zoom_out_button, &QPushButton::clicked, this, [this]() { adjustCameraZoom(1.0 / kCameraZoomFactor); });

    zoom_layout->addWidget(zoom_section_label);
    zoom_layout->addWidget(camera_zoom_label_);
    zoom_layout->addLayout(zoom_controls_layout);

    auto* pan_card = buildControlCard(preview_controls_group, "panControlCard");
    pan_card->setProperty("card", true);
    auto* pan_layout = new QVBoxLayout(pan_card);
    pan_layout->setContentsMargins(14, 14, 14, 14);
    pan_layout->setSpacing(10);

    auto* pan_section_label = new QLabel("Pan", pan_card);
    pan_section_label->setProperty("sectionTitle", true);

    camera_pan_label_ = new QLabel(pan_card);
    camera_pan_label_->setObjectName("cameraPanLabel");
    camera_pan_label_->setProperty("valueChip", true);
    camera_pan_label_->setWordWrap(true);

    auto* pan_controls_layout = new QGridLayout();
    pan_controls_layout->setHorizontalSpacing(8);
    pan_controls_layout->setVerticalSpacing(8);

    auto* pan_up_button = buildRingButton(pan_card, "panUpButton", "^", "Pan up", "Move target toward +Z.");
    auto* pan_left_button = buildRingButton(pan_card, "panLeftButton", "<", "Pan left", "Move target toward -X.");
    auto* pan_right_button = buildRingButton(pan_card, "panRightButton", ">", "Pan right", "Move target toward +X.");
    auto* pan_down_button = buildRingButton(pan_card, "panDownButton", "v", "Pan down", "Move target toward -Z.");

    pan_controls_layout->addWidget(pan_up_button, 0, 1);
    pan_controls_layout->addWidget(pan_left_button, 1, 0);
    pan_controls_layout->addWidget(pan_right_button, 1, 2);
    pan_controls_layout->addWidget(pan_down_button, 2, 1);

    connect(pan_up_button, &QPushButton::clicked, this, [this]() { adjustCameraPan(0.0, kCameraPanStep); });
    connect(pan_left_button, &QPushButton::clicked, this, [this]() { adjustCameraPan(-kCameraPanStep, 0.0); });
    connect(pan_right_button, &QPushButton::clicked, this, [this]() { adjustCameraPan(kCameraPanStep, 0.0); });
    connect(pan_down_button, &QPushButton::clicked, this, [this]() { adjustCameraPan(0.0, -kCameraPanStep); });

    pan_layout->addWidget(pan_section_label);
    pan_layout->addWidget(camera_pan_label_);
    pan_layout->addLayout(pan_controls_layout);

    auto* rotation_card = buildControlCard(preview_controls_group, "rotationControlCard");
    rotation_card->setProperty("card", true);
    auto* rotation_layout = new QVBoxLayout(rotation_card);
    rotation_layout->setContentsMargins(14, 14, 14, 14);
    rotation_layout->setSpacing(10);

    auto* rotation_section_label = new QLabel("Rotate", rotation_card);
    rotation_section_label->setProperty("sectionTitle", true);

    camera_rotation_label_ = new QLabel(rotation_card);
    camera_rotation_label_->setObjectName("cameraRotationLabel");
    camera_rotation_label_->setProperty("valueChip", true);
    camera_rotation_label_->setWordWrap(true);

    auto* rotation_controls_layout = new QGridLayout();
    rotation_controls_layout->setHorizontalSpacing(8);
    rotation_controls_layout->setVerticalSpacing(8);

    auto* rotate_up_button = buildRingButton(rotation_card, "rotateUpButton", "P+", "Pitch up", "Increase preview pitch.");
    auto* rotate_left_button = buildRingButton(rotation_card, "rotateLeftButton", "Y-", "Yaw left", "Decrease preview yaw.");
    auto* rotate_right_button = buildRingButton(rotation_card, "rotateRightButton", "Y+", "Yaw right", "Increase preview yaw.");
    auto* rotate_down_button = buildRingButton(rotation_card, "rotateDownButton", "P-", "Pitch down", "Decrease preview pitch.");

    rotation_controls_layout->addWidget(rotate_up_button, 0, 1);
    rotation_controls_layout->addWidget(rotate_left_button, 1, 0);
    rotation_controls_layout->addWidget(rotate_right_button, 1, 2);
    rotation_controls_layout->addWidget(rotate_down_button, 2, 1);

    connect(rotate_up_button, &QPushButton::clicked, this, [this]() { adjustCameraOrbit(0.0, kCameraOrbitStepDegrees); });
    connect(rotate_left_button, &QPushButton::clicked, this, [this]() { adjustCameraOrbit(-kCameraOrbitStepDegrees, 0.0); });
    connect(rotate_right_button, &QPushButton::clicked, this, [this]() { adjustCameraOrbit(kCameraOrbitStepDegrees, 0.0); });
    connect(rotate_down_button, &QPushButton::clicked, this, [this]() { adjustCameraOrbit(0.0, -kCameraOrbitStepDegrees); });

    rotation_layout->addWidget(rotation_section_label);
    rotation_layout->addWidget(camera_rotation_label_);
    rotation_layout->addLayout(rotation_controls_layout);

    auto* robot_card = buildControlCard(controls_body, "robotControlCard");
    robot_card->setProperty("card", true);
    robot_card->setMinimumWidth(210);
    robot_card->setMaximumWidth(260);
    robot_card->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Maximum);
    auto* robot_layout = new QVBoxLayout(robot_card);
    robot_layout->setContentsMargins(12, 12, 12, 12);
    robot_layout->setSpacing(8);

    auto* robot_section_label = new QLabel("Robot", robot_card);
    robot_section_label->setProperty("sectionTitle", true);

    robot_pose_label_ = new QLabel(robot_card);
    robot_pose_label_->setObjectName("robotPoseLabel");
    robot_pose_label_->setProperty("valueChip", true);
    robot_pose_label_->setWordWrap(true);

    auto* robot_translation_layout = new QGridLayout();
    robot_translation_layout->setHorizontalSpacing(8);
    robot_translation_layout->setVerticalSpacing(8);

    auto* robot_forward_button = buildRingButton(
        robot_card,
        "robotForwardButton",
        "^",
        "Move robot forward",
        "Move robot toward +Y.");
    auto* robot_back_button = buildRingButton(
        robot_card,
        "robotBackButton",
        "v",
        "Move robot back",
        "Move robot toward -Y.");
    auto* robot_left_button = buildRingButton(
        robot_card,
        "robotLeftButton",
        "<",
        "Move robot left",
        "Move robot toward -X.");
    auto* robot_right_button = buildRingButton(
        robot_card,
        "robotRightButton",
        ">",
        "Move robot right",
        "Move robot toward +X.");
    auto* robot_rise_button = buildRingButton(
        robot_card,
        "robotRiseButton",
        "Z+",
        "Raise robot",
        "Move robot toward +Z.");
    auto* robot_lower_button = buildRingButton(
        robot_card,
        "robotLowerButton",
        "Z-",
        "Lower robot",
        "Move robot toward -Z.");

    robot_translation_layout->addWidget(robot_forward_button, 0, 1, Qt::AlignCenter);
    robot_translation_layout->addWidget(robot_left_button, 1, 0, Qt::AlignCenter);
    robot_translation_layout->addWidget(robot_rise_button, 1, 1, Qt::AlignCenter);
    robot_translation_layout->addWidget(robot_right_button, 1, 2, Qt::AlignCenter);
    robot_translation_layout->addWidget(robot_back_button, 2, 1, Qt::AlignCenter);
    robot_translation_layout->addWidget(robot_lower_button, 3, 1, Qt::AlignCenter);
    robot_translation_layout->setColumnStretch(0, 1);
    robot_translation_layout->setColumnStretch(1, 1);
    robot_translation_layout->setColumnStretch(2, 1);

    connect(
        robot_forward_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(0.0, kRobotTranslationStepMeters, 0.0); });
    connect(
        robot_back_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(0.0, -kRobotTranslationStepMeters, 0.0); });
    connect(
        robot_left_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(-kRobotTranslationStepMeters, 0.0, 0.0); });
    connect(
        robot_right_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(kRobotTranslationStepMeters, 0.0, 0.0); });
    connect(
        robot_rise_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(0.0, 0.0, kRobotTranslationStepMeters); });
    connect(
        robot_lower_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotTranslation(0.0, 0.0, -kRobotTranslationStepMeters); });

    auto* robot_rotation_layout = new QHBoxLayout();
    robot_rotation_layout->setSpacing(8);
    auto* robot_rotate_left_button = buildRingButton(
        robot_card,
        "robotRotateLeftButton",
        "Y-",
        "Rotate robot left",
        "Decrease robot yaw.");
    auto* robot_rotate_right_button = buildRingButton(
        robot_card,
        "robotRotateRightButton",
        "Y+",
        "Rotate robot right",
        "Increase robot yaw.");
    robot_rotation_layout->addStretch(1);
    robot_rotation_layout->addWidget(robot_rotate_left_button);
    robot_rotation_layout->addWidget(robot_rotate_right_button);
    robot_rotation_layout->addStretch(1);

    connect(
        robot_rotate_left_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotYaw(-kRobotRotationStepDegrees); });
    connect(
        robot_rotate_right_button,
        &QPushButton::clicked,
        this,
        [this]() { adjustRobotYaw(kRobotRotationStepDegrees); });

    robot_layout->addWidget(robot_section_label);
    robot_layout->addWidget(robot_pose_label_);
    robot_layout->addLayout(robot_translation_layout);
    robot_layout->addLayout(robot_rotation_layout);

    preview_controls_layout->addWidget(scene_card);
    preview_controls_layout->addWidget(zoom_card);
    preview_controls_layout->addWidget(pan_card);
    preview_controls_layout->addWidget(rotation_card);
    preview_controls_layout->addStretch(1);

    controls_body_layout->addWidget(preview_controls_group, 1);
    controls_body_layout->addWidget(robot_card, 0, Qt::AlignTop);
    panel_layout->addWidget(controls_body);

    camera_controls_dock->setWidget(camera_controls_panel);
    addDockWidget(Qt::RightDockWidgetArea, camera_controls_dock);

    auto* bottom_status_bar = new QStatusBar(this);
    bottom_status_bar->setObjectName("renderStatusBar");
    bottom_status_bar->setSizeGripEnabled(false);

    render_status_label_ = new QLabel("render subscriber: starting...", bottom_status_bar);
    render_status_label_->setObjectName("renderStatusLabel");
    render_status_label_->setStyleSheet("font-size: 12px; font-weight: 600; color: #5f6368;");

    render_detail_label_ = new QLabel(bottom_status_bar);
    render_detail_label_->setObjectName("renderDetailLabel");
    render_detail_label_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    render_detail_label_->setStyleSheet("font-size: 12px; color: #5f6368;");

    bottom_status_bar->addWidget(render_status_label_);
    bottom_status_bar->addWidget(render_detail_label_, 1);
    setStatusBar(bottom_status_bar);

    render_worker_ = new RenderWorker(this);
    connect(render_worker_, &RenderWorker::statusChanged, this, &MainWindow::applyRenderStatus);
    connect(render_worker_, &RenderWorker::frameReady, this, &MainWindow::applyPreviewFrame);
    connect(render_worker_, &RenderWorker::previewCameraStateChanged, this, &MainWindow::applyPreviewCameraState);
    connect(render_worker_, &RenderWorker::previewSettingsChanged, this, &MainWindow::applyPreviewSettingsState);
    if (autoSubscribe)
    {
        render_worker_->subscribe();
    }

    render_detail_text_ = QStringLiteral("Waiting for frame metadata and payload subscriptions to come online.");
    refreshRenderDetailLabel();
    refreshCameraControlLabels();
    refreshRobotControlLabels();
}

void MainWindow::applyRenderStatus(const QString& summary, const QString& detail, bool isError)
{
    render_status_label_->setText(summary);
    render_status_label_->setToolTip(summary);
    render_detail_text_ = detail;
    render_detail_label_->setToolTip(detail);
    refreshRenderDetailLabel();

    if (!isError)
    {
        render_status_label_->setStyleSheet("color: #137333; font-size: 12px; font-weight: 600;");
        return;
    }

    render_status_label_->setStyleSheet("color: #b3261e; font-size: 12px; font-weight: 600;");
}

void MainWindow::applyPreviewFrame(const QImage& image, qint64 frameId)
{
    if (preview_viewport_ != nullptr)
    {
        preview_viewport_->setPreviewFrame(image, frameId);
    }
}

void MainWindow::applyPreviewCameraState(const PreviewCameraState& state)
{
    if (preview_viewport_ != nullptr)
    {
        preview_viewport_->setPreviewCameraState(state);
    }
}

void MainWindow::applyPreviewSettingsState(const PreviewSettingsState& state)
{
    scene_ply_path_ = state.plyPath;
    refreshSceneLabel();

    if (state.focalLengthPx >= kCameraMinFocalLengthPx)
    {
        camera_focal_length_px_ = state.focalLengthPx;
    }

    refreshCameraControlLabels();
}

void MainWindow::refreshRenderDetailLabel()
{
    if (render_detail_label_ == nullptr)
    {
        return;
    }

    const int available_width = std::max(render_detail_label_->width(), 120);
    const QFontMetrics metrics(render_detail_label_->font());
    render_detail_label_->setText(metrics.elidedText(render_detail_text_, Qt::ElideRight, available_width));
}

void MainWindow::adjustCameraZoom(double scaleFactor)
{
    camera_focal_length_px_ = std::clamp(
        camera_focal_length_px_ * scaleFactor,
        kCameraMinFocalLengthPx,
        kCameraMaxFocalLengthPx);
    refreshCameraControlLabels();
    if (render_worker_ != nullptr)
    {
        render_worker_->requestPreviewSettingsUpdate(
            static_cast<float>(camera_focal_length_px_),
            QString());
    }
}

void MainWindow::adjustCameraPan(double deltaX, double deltaZ)
{
    camera_pan_x_ += deltaX;
    camera_pan_z_ += deltaZ;
    refreshCameraControlLabels();
    sendPreviewCameraControl();
}

void MainWindow::adjustCameraOrbit(double deltaYawDegrees, double deltaPitchDegrees)
{
    camera_yaw_degrees_ += deltaYawDegrees;
    camera_yaw_degrees_ = std::remainder(camera_yaw_degrees_, 360.0);
    camera_pitch_degrees_ = std::clamp(
        camera_pitch_degrees_ + deltaPitchDegrees,
        -kCameraMaxPitchDegrees,
        kCameraMaxPitchDegrees);
    refreshCameraControlLabels();
    sendPreviewCameraControl();
}

void MainWindow::resetPreviewCameraValues()
{
    camera_focal_length_px_ = kCameraDefaultFocalLengthPx;
    camera_pan_x_ = 0.0;
    camera_pan_z_ = 0.0;
    camera_yaw_degrees_ = 0.0;
    camera_pitch_degrees_ = 0.0;
}

void MainWindow::resetPreviewCameraView()
{
    resetPreviewCameraValues();
    refreshCameraControlLabels();
    if (render_worker_ != nullptr)
    {
        render_worker_->requestPreviewSettingsUpdate(
            static_cast<float>(camera_focal_length_px_),
            QString());
    }
    sendPreviewCameraControl();
}

void MainWindow::adjustRobotTranslation(double deltaX, double deltaY, double deltaZ)
{
    robot_position_x_m_ += deltaX;
    robot_position_y_m_ += deltaY;
    robot_position_z_m_ = std::max(0.0, robot_position_z_m_ + deltaZ);
    refreshRobotControlLabels();
    sendRobotControl();
}

void MainWindow::adjustRobotYaw(double deltaYawDegrees)
{
    robot_yaw_degrees_ += deltaYawDegrees;
    robot_yaw_degrees_ = std::remainder(robot_yaw_degrees_, 360.0);
    refreshRobotControlLabels();
    sendRobotControl();
}

void MainWindow::browsePreviewScenePath()
{
    const QString selectedPath = QFileDialog::getOpenFileName(
        this,
        QStringLiteral("Open Scene"),
        scene_ply_path_,
        QStringLiteral("PLY Files (*.ply);;All Files (*)"));
    if (selectedPath.isEmpty())
    {
        return;
    }

    scene_ply_path_ = selectedPath;
    resetPreviewCameraValues();
    refreshCameraControlLabels();
    if (render_worker_ != nullptr)
    {
        render_worker_->requestPreviewSettingsUpdate(
            static_cast<float>(camera_focal_length_px_),
            scene_ply_path_);
    }
    sendPreviewCameraControl();
}

void MainWindow::sendPreviewCameraControl()
{
    if (render_worker_ != nullptr)
    {
        render_worker_->requestPreviewCameraControl(
            static_cast<float>(camera_pan_x_),
            0.0f,
            static_cast<float>(camera_pan_z_),
            static_cast<float>(camera_yaw_degrees_),
            static_cast<float>(camera_pitch_degrees_));
    }
}

void MainWindow::sendRobotControl()
{
    if (render_worker_ != nullptr)
    {
        render_worker_->requestRobotPoseControl(
            static_cast<float>(robot_position_x_m_),
            static_cast<float>(robot_position_y_m_),
            static_cast<float>(robot_position_z_m_),
            static_cast<float>(robot_yaw_degrees_));
    }
}

void MainWindow::refreshSceneLabel()
{
    if (current_scene_label_ == nullptr)
    {
        return;
    }

    const int available_width = std::max(current_scene_label_->width() - 24, 120);
    const QFontMetrics metrics(current_scene_label_->font());
    const QString elided_path = metrics.elidedText(scene_ply_path_, Qt::ElideMiddle, available_width);
    current_scene_label_->setText(QStringLiteral("Scene: %1").arg(elided_path));
    current_scene_label_->setToolTip(scene_ply_path_);
}

void MainWindow::refreshCameraControlLabels()
{
    refreshSceneLabel();

    if (camera_zoom_label_ != nullptr)
    {
        camera_zoom_label_->setText(
            QStringLiteral("Preview zoom: focal=%1px")
                .arg(camera_focal_length_px_, 0, 'f', 1));
    }

    if (camera_pan_label_ != nullptr)
    {
        camera_pan_label_->setText(
            QStringLiteral("Preview camera pan (radius units): x=%1 y=%2 z=%3")
                .arg(camera_pan_x_, 0, 'f', 2)
                .arg(0.0, 0, 'f', 2)
                .arg(camera_pan_z_, 0, 'f', 2));
    }

    if (camera_rotation_label_ != nullptr)
    {
        camera_rotation_label_->setText(
            QStringLiteral("Preview camera rotation: yaw=%1deg pitch=%2deg")
                .arg(camera_yaw_degrees_, 0, 'f', 1)
                .arg(camera_pitch_degrees_, 0, 'f', 1));
    }
}

void MainWindow::refreshRobotControlLabels()
{
    if (robot_pose_label_ != nullptr)
    {
        robot_pose_label_->setText(
            QStringLiteral("Robot pose: x=%1m y=%2m z=%3m yaw=%4deg")
                .arg(robot_position_x_m_, 0, 'f', 2)
                .arg(robot_position_y_m_, 0, 'f', 2)
                .arg(robot_position_z_m_, 0, 'f', 2)
                .arg(robot_yaw_degrees_, 0, 'f', 1));
    }
}

void MainWindow::resizeEvent(QResizeEvent* event)
{
    QMainWindow::resizeEvent(event);
    refreshRenderDetailLabel();
    refreshSceneLabel();
}

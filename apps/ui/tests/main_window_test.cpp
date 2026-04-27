#include "main_window.h"
#include "preview_viewport_widget.h"
#include "render_worker.h"

#include <QAction>
#include <QDockWidget>
#include <QImage>
#include <QLabel>
#include <QMenuBar>
#include <QPainter>
#include <QPushButton>
#include <QStatusBar>
#include <QtTest/QtTest>

class MainWindowTest : public QObject
{
    Q_OBJECT

private slots:
    void placesCameraControlsInRightDock();
    void rendersSubscriberStatusInBottomStatusBar();
    void labelsPreviewCameraUiClearly();
    void separatesPanAndRotateControls();
    void exposesSceneSelectionFromMenuBar();
    void exposesOptionBCameraActionButtons();
    void rendersPreviewGizmoWithLatestCameraStateFallback();
};

void MainWindowTest::placesCameraControlsInRightDock()
{
    MainWindow window(nullptr, false);

    auto* camera_controls_dock = window.findChild<QDockWidget*>("cameraControlsDock");
    QVERIFY(camera_controls_dock != nullptr);
    QCOMPARE(window.dockWidgetArea(camera_controls_dock), Qt::RightDockWidgetArea);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    QVERIFY(camera_pan_label != nullptr);
    QCOMPARE(camera_pan_label->parentWidget(), camera_controls_dock->widget());
}

void MainWindowTest::rendersSubscriberStatusInBottomStatusBar()
{
    MainWindow window(nullptr, false);

    auto* status_bar = window.statusBar();
    QVERIFY(status_bar != nullptr);

    auto* render_status_label = window.findChild<QLabel*>("renderStatusLabel");
    auto* render_detail_label = window.findChild<QLabel*>("renderDetailLabel");
    QVERIFY(render_status_label != nullptr);
    QVERIFY(render_detail_label != nullptr);
    QCOMPARE(render_status_label->parentWidget(), status_bar);
    QCOMPARE(render_detail_label->parentWidget(), status_bar);
    QCOMPARE(render_status_label->text(), QString("render subscriber: starting..."));
}

void MainWindowTest::labelsPreviewCameraUiClearly()
{
    MainWindow window(nullptr, false);

    auto* camera_controls_dock = window.findChild<QDockWidget*>("cameraControlsDock");
    QVERIFY(camera_controls_dock != nullptr);
    QCOMPARE(camera_controls_dock->windowTitle(), QString("Preview camera controls"));

    auto* preview_viewport = window.findChild<QWidget*>("previewViewport");
    QVERIFY(preview_viewport != nullptr);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(camera_pan_label->text().contains("Preview camera pan"));
}

void MainWindowTest::separatesPanAndRotateControls()
{
    MainWindow window(nullptr, false);

    auto* camera_pan_label = window.findChild<QLabel*>("cameraPanLabel");
    auto* camera_rotation_label = window.findChild<QLabel*>("cameraRotationLabel");
    QVERIFY(camera_pan_label != nullptr);
    QVERIFY(camera_rotation_label != nullptr);
    QVERIFY(camera_pan_label->text().contains("Preview camera pan"));
    QVERIFY(camera_rotation_label->text().contains("Preview camera rotation"));
}

void MainWindowTest::exposesSceneSelectionFromMenuBar()
{
    MainWindow window(nullptr, false);

    auto* open_scene_action = window.findChild<QAction*>("openSceneAction");
    auto* current_scene_label = window.findChild<QLabel*>("currentSceneLabel");
    auto* camera_zoom_label = window.findChild<QLabel*>("cameraZoomLabel");
    auto* legacy_scene_path_input = window.findChild<QWidget*>("previewScenePathInput");
    QVERIFY(window.menuBar() != nullptr);
    QVERIFY(open_scene_action != nullptr);
    QCOMPARE(open_scene_action->text(), QString("Open Scene..."));
    QVERIFY(current_scene_label != nullptr);
    QVERIFY(current_scene_label->text().contains("Current preview scene"));
    QVERIFY(camera_zoom_label != nullptr);
    QVERIFY(camera_zoom_label->text().contains("Preview zoom"));
    QVERIFY(legacy_scene_path_input == nullptr);
}

void MainWindowTest::exposesOptionBCameraActionButtons()
{
    MainWindow window(nullptr, false);

    auto* scene_view_button = window.findChild<QPushButton*>("sceneViewButton");
    auto* fit_button = window.findChild<QPushButton*>("fitSceneButton");
    auto* zoom_in_button = window.findChild<QPushButton*>("zoomInButton");
    auto* zoom_out_button = window.findChild<QPushButton*>("zoomOutButton");
    auto* pan_up_button = window.findChild<QPushButton*>("panUpButton");
    auto* pan_left_button = window.findChild<QPushButton*>("panLeftButton");
    auto* pan_right_button = window.findChild<QPushButton*>("panRightButton");
    auto* pan_down_button = window.findChild<QPushButton*>("panDownButton");
    auto* rotate_up_button = window.findChild<QPushButton*>("rotateUpButton");
    auto* rotate_left_button = window.findChild<QPushButton*>("rotateLeftButton");
    auto* rotate_right_button = window.findChild<QPushButton*>("rotateRightButton");
    auto* rotate_down_button = window.findChild<QPushButton*>("rotateDownButton");

    QVERIFY(scene_view_button != nullptr);
    QVERIFY(fit_button != nullptr);
    QVERIFY(zoom_in_button != nullptr);
    QVERIFY(zoom_out_button != nullptr);
    QVERIFY(pan_up_button != nullptr);
    QVERIFY(pan_left_button != nullptr);
    QVERIFY(pan_right_button != nullptr);
    QVERIFY(pan_down_button != nullptr);
    QVERIFY(rotate_up_button != nullptr);
    QVERIFY(rotate_left_button != nullptr);
    QVERIFY(rotate_right_button != nullptr);
    QVERIFY(rotate_down_button != nullptr);

    QCOMPARE(scene_view_button->text(), QString("Scene View"));
    QCOMPARE(fit_button->text(), QString("Fit"));
}

void MainWindowTest::rendersPreviewGizmoWithLatestCameraStateFallback()
{
    PreviewViewportWidget widget;
    widget.resize(400, 300);

    QImage preview_frame(400, 300, QImage::Format_RGB32);
    preview_frame.fill(Qt::white);
    widget.setPreviewFrame(preview_frame, 5);

    PreviewCameraState preview_camera_state;
    preview_camera_state.frameId = 4;
    preview_camera_state.cameraRole = "preview";
    preview_camera_state.eye = QVector3D(0.0f, -10.0f, 4.0f);
    preview_camera_state.target = QVector3D(0.0f, 0.0f, 0.0f);
    preview_camera_state.up = QVector3D(0.0f, 0.0f, 1.0f);
    preview_camera_state.sceneCenter = QVector3D(0.0f, 0.0f, 0.0f);
    preview_camera_state.sceneRadius = 5.0f;
    preview_camera_state.focalLengthPx = 900.0f;
    preview_camera_state.imageWidth = 400;
    preview_camera_state.imageHeight = 300;
    preview_camera_state.worldUpAxis = "z";
    preview_camera_state.gizmoEnabled = true;
    widget.setPreviewCameraState(preview_camera_state);

    QImage canvas(widget.size(), QImage::Format_ARGB32_Premultiplied);
    canvas.fill(Qt::transparent);

    QPainter painter(&canvas);
    widget.render(&painter);
    painter.end();

    const QColor sampled_color = canvas.pixelColor(320, 220);
    QVERIFY(sampled_color != QColor(Qt::white));
}

QTEST_MAIN(MainWindowTest)

#include "main_window_test.moc"

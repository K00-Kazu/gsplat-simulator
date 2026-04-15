#include "main_window.h"

#include <QDockWidget>
#include <QLabel>
#include <QStatusBar>
#include <QtTest/QtTest>

class MainWindowTest : public QObject
{
    Q_OBJECT

private slots:
    void placesCameraControlsInRightDock();
    void rendersSubscriberStatusInBottomStatusBar();
};

void MainWindowTest::placesCameraControlsInRightDock()
{
    MainWindow window(nullptr, false);

    auto* camera_controls_dock = window.findChild<QDockWidget*>("cameraControlsDock");
    QVERIFY(camera_controls_dock != nullptr);
    QCOMPARE(window.dockWidgetArea(camera_controls_dock), Qt::RightDockWidgetArea);

    auto* camera_offset_label = window.findChild<QLabel*>("cameraOffsetLabel");
    QVERIFY(camera_offset_label != nullptr);
    QCOMPARE(camera_offset_label->parentWidget(), camera_controls_dock->widget());
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

QTEST_MAIN(MainWindowTest)

#include "main_window_test.moc"

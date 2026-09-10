using System.Text.Json;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.IFC;
using DesignAutomationFramework;

namespace V365.RevitViewExtractor;

public sealed class App : IExternalDBApplication
{
    public ExternalDBApplicationResult OnStartup(ControlledApplication application)
    {
        DesignAutomationBridge.DesignAutomationReadyEvent += OnDesignAutomationReady;
        return ExternalDBApplicationResult.Succeeded;
    }

    public ExternalDBApplicationResult OnShutdown(ControlledApplication application)
    {
        DesignAutomationBridge.DesignAutomationReadyEvent -= OnDesignAutomationReady;
        return ExternalDBApplicationResult.Succeeded;
    }

    private static void OnDesignAutomationReady(
        object? sender,
        DesignAutomationReadyEventArgs eventArgs)
    {
        try
        {
            Execute(eventArgs.DesignAutomationData.RevitDoc);
            eventArgs.Succeeded = true;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            eventArgs.Succeeded = false;
        }
    }

    private static void Execute(Document document)
    {
        var parameters = JsonSerializer.Deserialize<ExtractorParameters>(
            File.ReadAllText("params.json"),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidOperationException("params.json is invalid.");

        var views = new FilteredElementCollector(document)
            .OfClass(typeof(View3D))
            .Cast<View3D>()
            .Where(view => !view.IsTemplate)
            .OrderBy(view => view.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(view => view.UniqueId, StringComparer.Ordinal)
            .ToArray();

        Directory.CreateDirectory("result");
        WriteViewCatalog(views);

        if (string.Equals(parameters.Mode, "list", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        if (!string.Equals(parameters.Mode, "export", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Mode must be 'list' or 'export'.");
        }

        var selected = SelectView(views, parameters);
        var options = new IFCExportOptions
        {
            FileVersion = IFCVersion.IFC4,
            FilterViewId = selected.Id,
        };
        options.AddOption("VisibleElementsOfCurrentView", "true");
        options.AddOption("UseActiveViewGeometry", "true");
        options.AddOption("ActiveViewId", selected.Id.Value.ToString());
        options.AddOption("ExportRoomsInView", "true");

        using var transaction = new Transaction(document, "V365 view-scoped IFC export");
        transaction.Start();
        var exported = document.Export("result", "model", options);
        transaction.RollBack();
        if (!exported)
        {
            throw new InvalidOperationException(
                $"Revit failed to export 3D view '{selected.Name}' ({selected.UniqueId}).");
        }

        File.WriteAllText(
            Path.Combine("result", "selection.json"),
            JsonSerializer.Serialize(
                new { name = selected.Name, unique_id = selected.UniqueId },
                new JsonSerializerOptions { WriteIndented = true }));
    }

    private static View3D SelectView(View3D[] views, ExtractorParameters parameters)
    {
        if (!string.IsNullOrWhiteSpace(parameters.ViewUniqueId))
        {
            var byId = views.Where(view =>
                string.Equals(view.UniqueId, parameters.ViewUniqueId, StringComparison.Ordinal)).ToArray();
            return byId.Length == 1
                ? byId[0]
                : throw new InvalidOperationException(
                    $"No non-template 3D view has unique id '{parameters.ViewUniqueId}'.");
        }

        if (string.IsNullOrWhiteSpace(parameters.ViewName))
        {
            throw new InvalidOperationException("viewName or viewUniqueId is required for export.");
        }

        var byName = views.Where(view =>
            string.Equals(view.Name, parameters.ViewName, StringComparison.OrdinalIgnoreCase)).ToArray();
        return byName.Length switch
        {
            1 => byName[0],
            0 => throw new InvalidOperationException(
                $"No non-template 3D view is named '{parameters.ViewName}'."),
            _ => throw new InvalidOperationException(
                $"Multiple non-template 3D views are named '{parameters.ViewName}'; select by unique id."),
        };
    }

    private static void WriteViewCatalog(IEnumerable<View3D> views)
    {
        var catalog = views.Select(view => new
        {
            name = view.Name,
            unique_id = view.UniqueId,
            is_perspective = view.IsPerspective,
        });
        File.WriteAllText(
            Path.Combine("result", "views.json"),
            JsonSerializer.Serialize(catalog, new JsonSerializerOptions { WriteIndented = true }));
    }

    private sealed record ExtractorParameters(
        string Mode = "list",
        string? ViewName = null,
        string? ViewUniqueId = null);
}
